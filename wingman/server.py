"""The Wingman server: one WebSocket per listener, plus the web console.

    uv run uvicorn wingman.server:app --host 0.0.0.0 --port 8787

A client (the web console or the Android app) sends microphone audio as binary frames of mono
PCM16 at 16 kHz and small JSON messages; it gets back JSON events and, rarely, a whisper.
The JSON routes under /api serve the app's other screens from Convex, so a phone that cannot
reach the database directly still works.
"""

import asyncio
import base64
import ipaddress
import json
import os
import time
from datetime import datetime

import numpy as np

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from wingman import agent, config, google, notion, slack, speakers, tts
from wingman import actions, connector, profile
from wingman.session import ACTIVE, Session
from wingman.store import Store, StoreError, convex_url

app = FastAPI(title="Wingman")

# The server is reachable from the internet through a tunnel. Sign-in returns must stay open,
# but everything that touches the owner's data has to come from the Wingman app, which sends
# a key with every request. Requests from this machine or the local network are not checked.
OPEN_PATHS = ("/oauth/", "/mcp/", "/.well-known/")  # the connector address carries its own token


def _from_outside(headers, client: str = "") -> bool:
    """Did this request come over the internet, rather than from this machine or its own network.
    Anything that passed through a proxy or a tunnel counts as the internet."""
    if "cf-connecting-ip" in headers or "cf-ray" in headers or "x-forwarded-for" in headers:
        return True
    try:
        address = ipaddress.ip_address(client)
    except ValueError:
        return False
    return not (address.is_loopback or address.is_private or address.is_link_local)


def _has_key(headers, query) -> bool:
    key = os.environ.get("WINGMAN_KEY", "")
    return bool(key) and (headers.get("x-wingman-key") == key or query.get("k") == key)


@app.middleware("http")
async def guard(request: Request, call_next):
    if (_from_outside(request.headers, request.client.host if request.client else "")
            and not request.url.path.startswith(OPEN_PATHS)
            and not _has_key(request.headers, request.query_params)):
        return JSONResponse({"detail": "This is a private Wingman server."}, status_code=401)
    return await call_next(request)
WEB = config.ROOT / "web"
_embedder: speakers.Embedder | None = None
_store: Store | None = None
ENROL_MIN_SECONDS = 5.0


def embedder() -> speakers.Embedder:
    global _embedder
    if _embedder is None:
        _embedder = speakers.Embedder()
    return _embedder


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


@app.get("/")
async def console():
    return FileResponse(WEB / "index.html")


@app.get("/config")
async def client_config():
    return {"convexUrl": convex_url(), "sampleRate": config.SAMPLE_RATE}


# --- Screens other than Live ---------------------------------------------------------------

async def _convex(kind: str, path: str, **args):
    try:
        call = store().query if kind == "query" else store().mutation
        return await call(path, **args)
    except StoreError as error:
        raise HTTPException(502, str(error)) from error


@app.get("/api/state")
async def state():
    settings, owner = await asyncio.gather(
        _convex("query", "settings:get"), _convex("query", "people:owner")
    )
    return {"settings": settings, "ownerEnrolled": bool(owner and owner.get("voiceprint")),
            "ownerName": owner["name"] if owner else None}


@app.get("/api/conversations")
async def conversations():
    """Finished conversations worth a recap, newest first."""
    return await _convex("query", "conversations:feed")


@app.get("/api/recap/{conversation}")
async def recap(conversation: str):
    if conversation == "latest":
        latest = await _convex("query", "conversations:latest")
        if not latest:
            return JSONResponse(None)
        conversation = latest["_id"]
    return await _convex("query", "conversations:recap", id=conversation)


@app.delete("/api/conversations/{conversation}")
async def delete_conversation(conversation: str):
    return await _convex("mutation", "conversations:remove", id=conversation)


@app.get("/api/home")
async def home():
    """Everything the Home screen shows, in one call."""
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    data, state_ = await asyncio.gather(
        _convex("query", "conversations:home", since=midnight.timestamp() * 1000),
        state(),
    )
    upcoming = await google.events(24)
    if data.get("now"):
        data["now"]["lastLine"] = ""  # the running transcript is not shown
    data["finished"] = await _convex("query", "tasks:finished", limit=15)
    return {**data, **state_, "next": upcoming[:3], "google": google.connected()}


@app.get("/api/clash")
async def clash(start: float, end: float):
    """Events on the calendar that overlap a proposed time (epoch milliseconds)."""
    out = []
    for event in await google.events(24 * 14):
        try:
            a = datetime.fromisoformat(event["start"]).timestamp() * 1000
            b = datetime.fromisoformat(event["end"]).timestamp() * 1000
        except (ValueError, TypeError):
            continue
        if a < end and b > start:
            out.append(event)
    return out


@app.post("/api/promises/{promise}/draft")
async def draft_promise(promise: str):
    every = await _convex("query", "promises:all")
    match = next((p for p in every if p["_id"] == promise), None)
    if match is None:
        raise HTTPException(404, "That promise no longer exists.")
    return {"message": await agent.draft(store(), match), "person": match.get("person")}


class Status(BaseModel):
    status: str


@app.get("/api/research")
async def research_list():
    return await _convex("query", "research:list")


@app.delete("/api/research/{study}")
async def research_delete(study: str):
    await _convex("mutation", "research:remove", id=study)
    return {"ok": True}


@app.get("/app.apk")
async def app_download():
    """The Android app, so a phone can install it from its browser."""
    apk = config.ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.exists():
        raise HTTPException(404, "The app has not been built yet.")
    return FileResponse(apk, media_type="application/vnd.android.package-archive", filename="wingman.apk")


@app.get("/api/tasks")
async def tasks():
    return await _convex("query", "tasks:open")


@app.post("/api/tasks/{task}")
async def set_task(task: str, body: Status):
    if body.status == "skip":  # a suggestion the owner did not want
        await _convex("mutation", "tasks:remove", id=task)
    else:
        await _convex("mutation", "tasks:setStatus", id=task, status=body.status)
    return {"ok": True}


@app.get("/api/tasks/done")
async def finished_tasks():
    """The record of to-dos that were marked done, newest first."""
    return await _convex("query", "tasks:finished")


class Answer(BaseModel):
    accept: bool


@app.post("/api/suggestions")
async def answer_suggestions(body: Answer):
    return {"count": await _convex("mutation", "tasks:answerSuggestions", accept=body.accept)}


# Everyone currently listening, so a reminder can be spoken wherever the owner is.
LISTENERS: set = set()


CHECKIN_EVERY = 3 * 3600.0  # a question in a quiet moment, at most this often
CHECKIN_EVERY_DEMO = 180.0
CHECKIN_QUIET = 60.0  # nobody has spoken for this long
CHECKIN_QUIET_DEMO = 15.0
_last_checkin = time.time()


async def _check_in(force: bool = False) -> str | None:
    """Ask the owner one question if it is a good moment (or now, when forced)."""
    global _last_checkin
    live_session = next((s for s in ACTIVE if not s.ended), None)
    if live_session is None:
        return None
    if not force:
        demo = live_session.governor.demo
        if time.time() - _last_checkin < (CHECKIN_EVERY_DEMO if demo else CHECKIN_EVERY):
            return None
        if (live_session.idle < (CHECKIN_QUIET_DEMO if demo else CHECKIN_QUIET) or live_session.busy
                or live_session.speaking or live_session.now < live_session.engaged_until):
            return None
        if not demo and not 8 <= datetime.now().hour < 22:
            return None
        _last_checkin = time.time()  # whatever happens next, do not look again for a while
        if (await store().query("settings:get")).get("checkins") is False:
            return None
    _last_checkin = time.time()
    question = await profile.checkin(store())
    if question and not live_session.ended:
        live_session.check_in(question)
        return question
    return None


_last_slack = 0.0


async def _sweep_slack(force: bool = False):
    """Every quarter of an hour, new Slack messages are read for things the owner must do."""
    global _last_slack
    if not slack.configured() or (not force and time.time() - _last_slack < 900):
        return
    _last_slack = time.time()

    async def sweep():
        try:
            if await actions.slack_todos(store()):
                for live_session in list(ACTIVE):
                    await live_session.emit({"type": "task"})
        except Exception as error:  # noqa: BLE001 - best effort, tried again next time
            print(f"slack sweep: {error}", flush=True)
    asyncio.create_task(sweep())


async def remind():
    """Every few seconds: speak any reminder that is due and any research that has finished,
    and now and then check in with the owner."""
    while True:
        await asyncio.sleep(5)
        if not ACTIVE:
            continue  # nobody to tell; it waits and is spoken when the owner is back
        try:
            await _sweep_slack()
            await _check_in()
            for task in await store().query("tasks:due", now=datetime.now().timestamp() * 1000):
                await store().mutation("tasks:markFired", id=task["_id"])
                for live_session in list(ACTIVE):
                    await live_session.emit({"type": "reminder", "id": task["_id"], "text": task["text"]})
                    live_session.say(f"Reminder: {task['text']}.", key=f"reminder:{task['_id']}")
            for study in await store().query("research:unannounced"):
                await store().mutation("research:markAnnounced", id=study["_id"])
                ok = study["status"] == "ready"
                line = (f"Your research on {study['topic']} is ready. Ask me for the short version."
                        if ok else f"I could not finish the research on {study['topic']}.")
                for live_session in list(ACTIVE):
                    await live_session.emit({"type": "research", "id": study["_id"], "topic": study["topic"], "ok": ok})
                    live_session.say(line, key=f"research:{study['_id']}")
        except Exception as error:  # noqa: BLE001 - the clock must keep running
            print(f"announcer: {error}", flush=True)


@app.on_event("startup")
async def start_clock():
    asyncio.create_task(remind())
    for source in profile.connected():  # catch up on anything connected while the profile was unwritten
        profile.schedule(store(), source, every=600)


@app.get("/api/promises")
async def promises():
    return await _convex("query", "promises:all")


@app.post("/api/promises/{promise}")
async def set_promise(promise: str, body: Status):
    await _convex("mutation", "promises:setStatus", id=promise, status=body.status)
    return {"ok": True}


@app.get("/api/people")
async def people():
    return await _convex("query", "people:list")


@app.get("/api/people/{person}")
async def person_page(person: str):
    """One person: who they are, what is open between you, when you spoke, and a briefing."""
    profile = await _convex("query", "people:profile", id=person)
    if profile is None:
        raise HTTPException(404, "Wingman no longer has that person.")
    for conversation in profile["conversations"]:
        conversation["lines"] = conversation["lines"][-40:]
    profile["brief"] = await agent.brief(profile)
    for conversation in profile["conversations"]:
        conversation.pop("lines", None)  # the page shows summaries, not transcripts
    return profile


@app.delete("/api/people/{person}")
async def delete_person(person: str):
    await _convex("mutation", "people:remove", id=person)
    return {"ok": True}


class Grade(BaseModel):
    grade: str | None = None


@app.post("/api/whispers/{whisper}/grade")
async def grade(whisper: str, body: Grade):
    await _convex("mutation", "whispers:grade", id=whisper, grade=body.grade)
    return {"ok": True}


class Settings(BaseModel):
    eagerness: str | None = None
    demo: bool | None = None
    checkins: bool | None = None


@app.post("/api/settings")
async def set_settings(body: Settings):
    await _convex("mutation", "settings:set", eagerness=body.eagerness, demo=body.demo, checkins=body.checkins)
    return await _convex("query", "settings:get")


@app.post("/api/wipe")
async def wipe():
    return await _convex("mutation", "settings:wipe")


# --- The agent you talk to -------------------------------------------------------------------

class Message(BaseModel):
    text: str
    speak: bool = False


async def _answer(text: str, speak: bool) -> dict:
    answer = await agent.chat(store(), text[:1000])
    if speak:
        try:
            pcm = await tts.synthesize(agent.spoken(answer)[:600])
            answer["audio"] = base64.b64encode(pcm).decode()
            answer["sampleRate"] = config.SAMPLE_RATE
        except Exception:  # noqa: BLE001 - the text answer is still returned
            answer["audio"] = None
    return answer


@app.post("/api/chat")
async def chat(body: Message):
    return {"heard": body.text, **await _answer(body.text, body.speak)}


@app.post("/api/chat/voice")
async def chat_voice(request: Request):
    """Push-to-talk: the body is mono PCM16 at 16 kHz; the answer comes back with audio."""
    pcm = await request.body()
    if len(pcm) < config.SAMPLE_RATE:  # under half a second
        raise HTTPException(400, "That was too short to hear.")
    try:
        heard = await agent.transcribe(pcm)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(502, f"Could not transcribe: {error}") from error
    if not heard:
        return {"heard": "", "reply": "I did not catch that.", "steps": [], "sources": []}
    return {"heard": heard, **await _answer(heard, True)}


@app.get("/api/integrations")
async def integrations():
    """Which outside accounts are set up and connected."""
    phone = google.device()
    return {"phone": {"events": len(phone.get("events", [])) if "events" in phone else None,
                      "contacts": len(phone.get("contacts", [])) if "contacts" in phone else None},
            "public": os.environ.get("PUBLIC_URL"),
            "notion": await notion.about(),
            "slack": await slack.about(),
            "google": {"configured": google.configured(), "connected": google.connected(),
                       "account": google.account(), "canBook": google.can_book(), "docs": google.can_read_docs(),
                       "signIn": "http://localhost:8787/oauth/google/start"}}


class Device(BaseModel):
    events: list | None = None
    contacts: list | None = None


@app.post("/api/device")
async def device_sync(body: Device):
    """The phone shares its own calendar and contacts, once the owner allows it."""
    saved = google.save_device(body.events, body.contacts)
    profile.schedule(store(), "Phone", every=6 * 3600)
    return saved


@app.get("/oauth/google/start")
async def google_start():
    if not google.configured():
        return HTMLResponse(PAGE % ("Google is not set up yet",
            "Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to the .env file in the Wingman folder, then restart the server."))
    return RedirectResponse(google.sign_in_url())


@app.get("/oauth/google/callback")
async def google_callback(code: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(PAGE % ("Google was not connected", error or "No code came back from Google."))
    try:
        who = await google.finish_sign_in(code)
    except Exception as problem:  # noqa: BLE001 - shown to the person signing in
        return HTMLResponse(PAGE % ("Google was not connected", str(problem)))
    profile.schedule(store(), "Google")  # a new account is read at once for what it shows about the owner
    return HTMLResponse(PAGE % ("Google is connected",
        f"Wingman can now read the calendar, contacts and mail of {who}. You can close this tab."))


@app.get("/oauth/slack/start")
async def slack_start():
    if not slack.can_sign_in():
        return HTMLResponse(PAGE % ("Slack sign-in is not set up yet",
            "Add SLACK_CLIENT_ID, SLACK_CLIENT_SECRET and an https SLACK_REDIRECT_URI to the .env file, then restart the server."))
    return RedirectResponse(slack.sign_in_url())


@app.get("/oauth/slack/callback")
async def slack_callback(code: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(PAGE % ("Slack was not connected", error or "No code came back from Slack."))
    try:
        team = await slack.finish_sign_in(code)
    except Exception as problem:  # noqa: BLE001 - shown to the person signing in
        return HTMLResponse(PAGE % ("Slack was not connected", str(problem)))
    profile.schedule(store(), "Slack")
    await _sweep_slack(force=True)  # and its messages are read for to-dos straight away
    return HTMLResponse(PAGE % ("Slack is connected", f"Wingman can now search {team} and send messages you approve. Go back to the Wingman app."))


@app.delete("/api/integrations/slack")
async def slack_disconnect():
    slack.disconnect()
    return {"ok": True}


class Message_(BaseModel):
    person: str
    text: str


@app.post("/api/slack/send")
async def slack_send(body: Message_):
    """Sends a drafted message as the owner, only because they tapped Send."""
    try:
        return {"sent": await slack.send(body.person, body.text)}
    except Exception as problem:  # noqa: BLE001
        raise HTTPException(400, str(problem)) from problem


@app.get("/oauth/notion/start")
async def notion_start():
    if not notion.can_sign_in():
        return HTMLResponse(PAGE % ("Notion sign-in is not set up yet",
            "Add NOTION_CLIENT_ID and NOTION_CLIENT_SECRET from a public Notion integration to the .env file, then restart the server."))
    return RedirectResponse(notion.sign_in_url())


@app.get("/oauth/notion/callback")
async def notion_callback(code: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(PAGE % ("Notion was not connected", error or "No code came back from Notion."))
    try:
        workspace = await notion.finish_sign_in(code)
    except Exception as problem:  # noqa: BLE001 - shown to the person signing in
        return HTMLResponse(PAGE % ("Notion was not connected", str(problem)))
    profile.schedule(store(), "Notion")
    return HTMLResponse(PAGE % ("Notion is connected",
        f"Wingman can now read the pages you chose in {workspace}. Go back to the Wingman app."))


@app.delete("/api/integrations/notion")
async def notion_disconnect():
    notion.disconnect()
    return {"ok": True}


class Code(BaseModel):
    code: str


@app.post("/api/google/code")
async def google_code(body: Code):
    """The app's "Continue with Google" button hands over a one-time code; keep the connection."""
    if not google.configured():
        raise HTTPException(400, "Google is not set up on the server.")
    try:
        account = await google.finish_sign_in(body.code, redirect="")
        profile.schedule(store(), "Google")
        return {"account": account}
    except Exception as problem:  # noqa: BLE001 - shown in the app
        raise HTTPException(400, str(problem)) from problem


@app.delete("/api/integrations/google")
async def google_disconnect():
    google.disconnect()
    return {"ok": True}


@app.get("/api/calendar")
async def calendar():
    return await google.events()


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wingman</title><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#070B1C;color:#fff;
font-family:Georgia,serif"><div style="max-width:520px;padding:32px"><h1 style="font-weight:400;font-size:44px;margin:0 0 12px">%s</h1>
<p style="font:16px/1.5 system-ui,sans-serif;color:#AEB6D6">%s</p></div></body>"""


class Import(BaseModel):
    source: str = "Typed"
    text: str


@app.post("/api/import")
async def import_memory(body: Import):
    if len(body.text.strip()) < 20:
        raise HTTPException(400, "Paste what the other assistant remembers about you first.")
    try:
        return await agent.import_memory(store(), body.source[:40], body.text)
    except Exception as problem:  # noqa: BLE001 - told to the person, not swallowed
        raise HTTPException(502, f"Could not read that: {problem}") from problem


@app.get("/api/profile")
async def get_profile():
    """The written-up picture of the owner, and which sources it draws on."""
    counts: dict[str, int] = {}
    for memory in await _convex("query", "memories:list"):
        counts[memory["source"]] = counts.get(memory["source"], 0) + 1
    return {"profile": await profile.get(store()), "connected": profile.connected(),
            "building": profile.BUILDING["on"], "reading": profile.BUILDING["reading"], "facts": counts}


@app.post("/api/profile/build")
async def build_profile():
    """Start reading every connected account for what it shows about the owner; returns at once."""
    profile.build(store())
    return {"building": True, "connected": profile.connected()}


@app.post("/api/profile/refresh")
async def refresh_profile():
    """Read every connected account again and rewrite the profile."""
    try:
        return {"profile": await profile.refresh(store()), "connected": profile.connected()}
    except Exception as problem:  # noqa: BLE001 - told to the person
        raise HTTPException(502, f"Could not rebuild the profile: {problem}") from problem


@app.post("/api/checkin")
async def check_in_now():
    """Ask the owner a question now, wherever they are listening."""
    return {"question": await _check_in(force=True)}


# --- Wingman as a connector for Claude and ChatGPT ----------------------------------------

@app.post("/mcp/{secret}")
async def connector_call(secret: str, request: Request):
    """Another assistant talking to Wingman (Model Context Protocol, one JSON reply per call)."""
    if secret != connector.token():
        raise HTTPException(404, "Not found")
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if isinstance(body, list):
        replies = [r for r in [await connector.handle(store(), m) for m in body if isinstance(m, dict)] if r]
        return JSONResponse(replies) if replies else Response(status_code=202)
    answer = await connector.handle(store(), body) if isinstance(body, dict) else None
    if answer and (body.get("method") == "tools/call"):
        for live_session in list(ACTIVE):  # the app's screens pick up what just arrived
            await live_session.emit({"type": "task"})
    return JSONResponse(answer) if answer else Response(status_code=202)


@app.get("/mcp/{secret}")
async def connector_stream(secret: str):
    return Response(status_code=405, headers={"Allow": "POST"})  # no server-sent stream is offered


@app.get("/api/connector")
async def connector_address():
    """The address to paste into Claude or ChatGPT as a custom connector."""
    return {"url": connector.address(), "name": "Wingman"}


@app.get("/api/memories")
async def memories():
    return await _convex("query", "memories:list")


@app.delete("/api/memories/{memory}")
async def delete_memory(memory: str):
    await _convex("mutation", "memories:remove", id=memory)
    return {"ok": True}


@app.get("/api/chats")
async def chats():
    return await _convex("query", "chats:recent", limit=60)


@app.delete("/api/chats")
async def clear_chats():
    return {"removed": await _convex("mutation", "chats:clear")}


# How long nobody speaks before always-on listening closes one conversation and starts the next.
ROLL_AFTER_GOODBYE = 8.0  # after "bye" or "talk later", this much silence is enough
ROLL_AFTER = 75.0
ROLL_AFTER_DEMO = 20.0


# --- Live ----------------------------------------------------------------------------------

@app.websocket("/ws")
async def live(socket: WebSocket):
    if (_from_outside(socket.headers, socket.client.host if socket.client else "")
            and not _has_key(socket.headers, socket.query_params)):
        await socket.close(code=1008)
        return
    await socket.accept()
    session: Session | None = None
    enrolling: bytearray | None = None
    enrol_name = "Me"
    lock = asyncio.Lock()
    background: set[asyncio.Task] = set()
    frames = 0

    async def emit(event: dict):
        if event.get("type") == "audio":
            event = {**event, "pcm": base64.b64encode(event["pcm"]).decode(),
                     "sampleRate": config.SAMPLE_RATE}
        async with lock:
            try:
                await socket.send_text(json.dumps(event))
            except (RuntimeError, WebSocketDisconnect):
                pass  # the listener went away; the session is ended below

    LISTENERS.add(emit)
    try:
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if enrolling is not None:
                    enrolling += message["bytes"]
                elif session is not None:
                    await session.feed(message["bytes"])
                    frames += 1
                    if frames % 100 == 0:  # every ten seconds: is sound arriving?
                        print(f"audio: {session.now:.0f}s loudest={session.peak} lines={len(session.lines)}",
                              flush=True)
                    limit = ROLL_AFTER_DEMO if session.governor.demo else ROLL_AFTER
                    if session.said_goodbye:
                        limit = min(limit, ROLL_AFTER_GOODBYE)  # the conversation was wrapped up
                    if session.ended:
                        session = None
                    elif session.lines and session.idle > limit and not session.busy:
                        # Always on: a long silence ends this conversation; its recap is
                        # written in the background while a fresh one starts listening.
                        finished, session = session, Session(
                            store(), emit, embedder(), eagerness=session.governor.eagerness,
                            demo=session.governor.demo)
                        closing = asyncio.create_task(finished.end(rolling=True))
                        background.add(closing)
                        closing.add_done_callback(background.discard)
                        try:
                            await session.start(continued=True)
                            session.continue_from(finished)
                        except Exception as error:  # noqa: BLE001
                            session = None
                            await emit({"type": "error", "message": f"Could not continue: {error}"})
                            await emit({"type": "ended", "conversation": None})
                continue
            try:
                command = json.loads(message.get("text") or "{}")
            except ValueError:
                continue
            kind = command.get("type")
            if kind == "start" and session is None:
                settings = await store().query("settings:get")
                session = Session(store(), emit, embedder(),
                                  eagerness=settings.get("eagerness", "normal"),
                                  demo=bool(settings.get("demo")))
                try:
                    # One pair of ears at a time: the device that just started takes over,
                    # otherwise two phones in a room would each hear and each answer.
                    for other in list(ACTIVE):
                        await other.emit({"type": "superseded"})
                        closing = asyncio.create_task(other.end(rolling=True))
                        background.add(closing)
                        closing.add_done_callback(background.discard)
                    await session.start()
                    await store().mutation("settings:set", listening=True)
                except Exception as error:  # noqa: BLE001 - shown on the screen
                    session = None
                    await emit({"type": "error", "message": f"Could not start: {error}"})
            elif kind == "stop" and session is not None:
                ending, session = session, None
                await emit({"type": "ending"})
                try:
                    await ending.end()
                except Exception as error:  # noqa: BLE001 - the listener must still be told
                    await emit({"type": "error", "message": f"Ending failed: {error}"})
                    await emit({"type": "ended", "conversation": None})
                await store().mutation("settings:set", listening=False)
            elif kind == "ask" and session is not None and command.get("text"):
                await session.ask(str(command["text"])[:300])
            elif kind == "enroll_start" and session is None:
                enrolling, enrol_name = bytearray(), str(command.get("name") or "Me")[:60]
                await emit({"type": "enrolling"})
            elif kind == "enroll_stop" and enrolling is not None:
                clip, enrolling = bytes(enrolling), None
                seconds = len(clip) / 2 / config.SAMPLE_RATE
                if seconds < ENROL_MIN_SECONDS:
                    await emit({"type": "enrolled", "ok": False,
                                "message": f"Only {seconds:.0f} s recorded; read for at least "
                                           f"{ENROL_MIN_SECONDS:.0f} s."})
                elif int(np.abs(np.frombuffer(clip, dtype=np.int16)).max(initial=0)) < 800:
                    await emit({"type": "enrolled", "ok": False,
                                "message": "Wingman could not hear you. Check the microphone "
                                           "and try again."})
                else:
                    vector = await asyncio.to_thread(embedder().embed, clip)
                    await store().mutation("people:upsert", name=enrol_name, isOwner=True,
                                           voiceprint=vector.tolist(), voiceSeconds=seconds)
                    await emit({"type": "enrolled", "ok": True, "seconds": seconds})
    except WebSocketDisconnect:
        pass
    finally:
        LISTENERS.discard(emit)
        if session is not None:
            await session.end()
            await store().mutation("settings:set", listening=False)
