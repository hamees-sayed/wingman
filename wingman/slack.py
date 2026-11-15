"""The owner's Slack: search what was said, and send a message they approved.

Wingman acts as the owner in Slack, with a user token. It reads by searching messages when
the owner is reaching for something, planning or researching. It sends only when the owner
taps Send on a draft; nothing is ever posted on its own.

Two ways to connect:
  - anyone: the "Connect Slack" button, using SLACK_CLIENT_ID and SLACK_CLIENT_SECRET from a
    Slack app. Slack only returns to an https address, set as SLACK_REDIRECT_URI.
  - the owner alone: a user token from their own Slack app, as SLACK_USER_TOKEN.
"""

import json
import os
import time
from urllib.parse import urlencode

import httpx

from wingman import config

API = "https://slack.com/api"
TOKEN = config.DATA_DIR / "slack-token.json"
# Slack's granular search scopes, as offered to apps created today (the single search:read
# scope is the older form). These match what the Wingman Slack app is configured with.
SCOPES = ("search:read.public,search:read.private,search:read.im,search:read.mpim,search:read.users,"
          "users:read,chat:write,channels:history,channels:read,groups:history,groups:read,"
          "im:history,mpim:history")

_about: tuple[float, dict] | None = None
_users: tuple[float, list] | None = None


def redirect() -> str:
    return os.environ.get("SLACK_REDIRECT_URI", "")


def can_sign_in() -> bool:
    return bool(os.environ.get("SLACK_CLIENT_ID") and os.environ.get("SLACK_CLIENT_SECRET") and redirect())


def _token() -> str | None:
    if TOKEN.exists():
        try:
            return json.loads(TOKEN.read_text()).get("access_token")
        except ValueError:
            return None
    return os.environ.get("SLACK_USER_TOKEN") or None


def configured() -> bool:
    return _token() is not None


async def _call(method: str, params: dict | None = None, timeout: float = 10) -> dict | None:
    token = _token()
    if token is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{API}/{method}", data=params or {},
                                         headers={"Authorization": f"Bearer {token}"})
        data = response.json()
        return data if data.get("ok") else None
    except (httpx.HTTPError, ValueError):
        return None


def sign_in_url() -> str:
    return "https://slack.com/oauth/v2/authorize?" + urlencode({
        "client_id": os.environ["SLACK_CLIENT_ID"], "user_scope": SCOPES, "redirect_uri": redirect(),
    })


async def finish_sign_in(code: str) -> str:
    """Trade Slack's code for this person's token."""
    global _about, _users
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{API}/oauth.v2.access", data={
            "client_id": os.environ["SLACK_CLIENT_ID"], "client_secret": os.environ["SLACK_CLIENT_SECRET"],
            "code": code, "redirect_uri": redirect(),
        })
    data = response.json()
    token = (data.get("authed_user") or {}).get("access_token")
    if not data.get("ok") or not token:
        raise RuntimeError(f"Slack refused the sign-in: {data.get('error', 'no token returned')}")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps({"access_token": token, "team": (data.get("team") or {}).get("name")}))
    TOKEN.chmod(0o600)
    _about = _users = None
    return (data.get("team") or {}).get("name") or "your Slack"


def disconnect():
    global _about, _users
    TOKEN.unlink(missing_ok=True)
    _about = _users = None


async def about() -> dict:
    """Whether Slack is connected, and to which workspace and person."""
    global _about
    if _about and time.time() - _about[0] < 30:
        return _about[1]
    state = {"connected": False, "workspace": None, "user": None, "signIn": can_sign_in(), "own": TOKEN.exists()}
    me = await _call("auth.test")
    if me:
        state.update(connected=True, workspace=me.get("team"), user=me.get("user"))
    _about = (time.time(), state)
    return state


async def _people() -> list[dict]:
    global _users
    if _users and time.time() - _users[0] < 900:
        return _users[1]
    data = await _call("users.list", {"limit": "500"})
    people = [{"id": m["id"], "name": m.get("real_name") or m.get("name", ""),
               "handle": (m.get("profile") or {}).get("display_name") or m.get("name", "")}
              for m in (data or {}).get("members", []) if not m.get("deleted") and not m.get("is_bot")]
    _users = (time.time(), people)
    return people


async def search(query: str, count: int = 6, timeout: float = 8) -> list[dict]:
    """Messages matching the words: who said it, where, and the text.

    Uses Slack's current search (the one the granular scopes grant), and falls back to the
    older search for tokens that carry the single search:read scope instead.
    """
    data = await _call("assistant.search.context", {
        "query": query, "limit": str(count), "content_types": "messages",
        "channel_types": "public_channel,private_channel,mpim,im",
    }, timeout)
    out = []
    for match in ((data or {}).get("results") or {}).get("messages", []):
        out.append({"who": match.get("author_name") or match.get("author_user_id") or "someone",
                    "where": match.get("channel_name") or "",
                    "text": (match.get("content") or match.get("text") or "")[:500]})
    if out or data is not None:
        return out
    data = await _call("search.messages", {"query": query, "count": str(count), "sort": "timestamp"}, timeout)
    for match in ((data or {}).get("messages") or {}).get("matches", []):
        out.append({"who": match.get("username") or "someone", "where": (match.get("channel") or {}).get("name", ""),
                    "text": (match.get("text") or "")[:500]})
    return out


async def me() -> dict:
    """The owner's own Slack profile: name, title, workspace, time zone."""
    who = await _call("auth.test")
    if not who:
        return {}
    info = ((await _call("users.info", {"user": who.get("user_id", "")})) or {}).get("user") or {}
    profile = info.get("profile") or {}
    return {"name": info.get("real_name") or who.get("user"), "title": profile.get("title"),
            "workspace": who.get("team"), "time zone": info.get("tz")}


async def mine(count: int = 30) -> list[dict]:
    """Messages the owner wrote recently, to learn what they work on and with whom."""
    return await search("from:me", count=min(count, 20), timeout=15)


SEEN = config.DATA_DIR / "slack-seen.json"  # the newest message already read for to-dos


async def recent(days: float = 3.0, fresh_only: bool = True) -> tuple[list[dict], str]:
    """Recent messages that could hold work for the owner: ones that mention them, ones sent
    to them directly, and ones they wrote (for what they said they would do). Returns the
    messages, oldest first, and the owner's Slack name. With fresh_only, messages already
    read on an earlier pass are left out."""
    who = await _call("auth.test")
    if not who:
        return [], ""
    since = time.time() - days * 86400
    if fresh_only and SEEN.exists():
        try:
            since = max(since, float(json.loads(SEEN.read_text()).get("ts", 0)))
        except ValueError:
            pass
    found: dict[str, dict] = {}
    for query, kind in ((f"<@{who['user_id']}>", "mentions the owner"), ("to:me", "sent to the owner directly"),
                        ("from:me", "written by the owner")):
        data = await _call("assistant.search.context", {
            "query": query, "limit": "20", "content_types": "messages", "sort": "timestamp", "sort_dir": "desc",
            "channel_types": "public_channel,private_channel,mpim,im"}, 15)
        for m in ((data or {}).get("results") or {}).get("messages", []):
            ts = float(m.get("message_ts") or 0)
            text = (m.get("content") or "").strip()
            if ts <= since or not text or (m.get("is_author_bot") and kind != "mentions the owner"):
                continue
            found.setdefault(m.get("permalink") or f"{ts}", {
                "ts": ts, "who": m.get("author_name") or "someone", "where": m.get("channel_name") or "a direct message",
                "text": text[:700], "kind": kind, "bot": bool(m.get("is_author_bot"))})
    messages = sorted(found.values(), key=lambda m: m["ts"])
    return messages, who.get("user") or ""


def mark_read(messages: list[dict]):
    if messages:
        SEEN.write_text(json.dumps({"ts": max(m["ts"] for m in messages)}))


async def send(person: str, text: str) -> str:
    """Sends a direct message as the owner. Returns the name it went to, or raises."""
    wanted = person.strip().lower()
    people = await _people()
    match = next((p for p in people if p["name"].lower() == wanted or p["handle"].lower() == wanted), None) or next(
        (p for p in people if wanted and (wanted in p["name"].lower() or p["name"].lower().split(" ")[0] == wanted.split(" ")[0])), None)
    if match is None:
        raise RuntimeError(f"Nobody called {person} was found in your Slack.")
    # Posting to a person's ID as the owner lands in the direct message between the two.
    if not await _call("chat.postMessage", {"channel": match["id"], "text": text}):
        raise RuntimeError("Slack did not accept the message.")
    return match["name"]
