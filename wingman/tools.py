"""Tool registry for the direct chat agent.

Tools wrap existing integrations and actions. Each tool returns plain text for the model, and
may also return `done` items for the app to refresh lists.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from wingman import google, notion, recall, slack, users
from wingman.actions import carry_out, slack_todos
from wingman.actions import confirmation as actions_confirmation
from wingman.store import Store, StoreError

ToolFn = Callable[[Store, dict[str, Any]], Awaitable["ToolResult"]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: ToolFn


@dataclass
class ToolResult:
    text: str
    done: list[dict]


def _params(required: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def _one(text: str) -> ToolResult:
    return ToolResult(text=text, done=[])


def _clip(text: str, limit: int = 220) -> str:
    text = str(text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + "…"


def _fmt_due(ms: float | None) -> str:
    if not ms:
        return ""
    when = datetime.fromtimestamp(ms / 1000)
    return f" (due {when.strftime('%a %H:%M')})"


def _clean_done(items: list[dict]) -> list[dict]:
    done = []
    for row in items:
        if not isinstance(row, dict):
            continue
        done.append({
            "id": row.get("id") or "",
            "kind": row.get("kind") or "",
            "text": str(row.get("text") or "").strip(),
            "due": row.get("due"),
            "dueText": row.get("dueText"),
        })
    return done


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


async def _act(store: Store, request: dict[str, Any]) -> ToolResult:
    try:
        raw_done = await carry_out(store, [request])
    except Exception as error:  # noqa: BLE001
        return _one(f"Action failed: {error}")
    done = _clean_done(raw_done)
    if not done:
        return _one("Nothing changed.")
    return ToolResult(text=describe_done(done), done=done)


async def slack_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    if not slack.configured():
        return _one("Slack is not connected.")
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a Slack search query.")
    try:
        hits = await slack.search(query, strict=True)
    except RuntimeError as error:
        return _one(str(error))
    if not hits:
        return _one("No Slack messages found.")
    return _one("\n".join(
        f"- {h['who']} in {h.get('where') or 'a direct message'}: {_clip(h['text'])}" for h in hits[:12]))


async def slack_action_items_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store, args
    if not slack.configured():
        return _one("Slack is not connected.")
    try:
        messages, name = await slack.recent(days=3.0, fresh_only=False, strict=True)
    except RuntimeError as error:
        return _one(str(error))
    if not messages:
        return _one("No recent Slack messages that need the owner were found.")
    shown = "\n".join(
        f"- {m['who']} in {m['where']} ({m['kind']}): {_clip(m['text'])}" for m in messages[-16:])
    return _one(f"Owner Slack name: {name or 'unknown'}\n{shown}")


async def calendar_events_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    days = max(1, min(30, int(args.get("days") or 3)))
    try:
        events = await google.events(days * 24, strict=True)
    except RuntimeError as error:
        return _one(str(error))
    if not events:
        return _one(f"No calendar events found in the next {days} days.")
    return _one(google.describe(events[:20]))


async def todo_list_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del args
    try:
        todo = await store.query("tasks:open")
    except StoreError as error:
        return _one(f"Could not read to-dos: {error}")
    if not todo:
        return _one("The to-do list is empty.")
    return _one("\n".join(f"- {t['text']}{_fmt_due(t.get('due'))}" for t in todo[:40]))


async def promises_list_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del args
    try:
        rows = await store.query("promises:open")
    except StoreError as error:
        return _one(f"Could not read promises: {error}")
    if not rows:
        return _one("No open promises.")
    lines = []
    for row in rows[:40]:
        who = f"You owe {row['person']}" if row.get("by") == "you" else f"{row['person']} owes you"
        lines.append(f"- {who}: {_clip(row.get('what') or '', 120)}")
    return _one("\n".join(lines))


async def people_lookup_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    name = str(args.get("name") or "").strip().lower()
    if not name:
        return _one("Please provide a name to look up.")
    try:
        people = await store.query("people:list")
    except StoreError as error:
        return _one(f"Could not read people: {error}")
    hits = [p for p in people if name in str(p.get("name") or "").lower()]
    if not hits:
        contacts = await google.contacts()
        hits = [{"name": row.get("name"), "about": row.get("about")} for row in contacts
                if name in str(row.get("name") or "").lower()]
    if not hits and slack.configured():
        # Colleagues the owner has never named aloud are still in their Slack workspace.
        try:
            hits = [{"name": row["name"], "about": "in the owner's Slack workspace"
                     + (f", @{row['handle']}" if row.get("handle") else "")}
                    for row in await slack._people() if name in row["name"].lower()]
        except Exception:  # noqa: BLE001 - a directory lookup failing is just "not found there"
            hits = []
    if not hits:
        return _one(f"No person found matching {name}.")
    lines = []
    for person in hits[:10]:
        about = str(person.get("about") or "").strip()
        lines.append(f"- {person['name']}" + (f": {_clip(about, 200)}" if about else ""))
        if not person.get("_id"):
            continue
        # Everything Wingman holds on them: when the owner spoke with them, what it was
        # about, and what stands between them.
        try:
            page = await store.query("people:profile", id=person["_id"])
        except StoreError:
            page = None
        if not page:
            continue
        for promise in page.get("owe") or []:
            lines.append(f"    the owner owes them: {_clip(promise.get('what') or '', 120)}")
        for promise in page.get("owed") or []:
            lines.append(f"    they owe the owner: {_clip(promise.get('what') or '', 120)}")
        # The conversations they were part of, fullest first: a one-line exchange about them
        # says less than the conversation the owner actually had with them.
        talks = sorted(page.get("conversations") or [], key=lambda talk: -len(talk.get("lines") or []))
        for position, talk in enumerate(talks[:3]):
            when = datetime.fromtimestamp(talk["startedAt"] / 1000).strftime("%a %d %b %H:%M")
            lines.append(f"    Conversation with them, \"{talk.get('title')}\" ({when}): {_clip(talk.get('summary') or '', 400)}")
            said = talk.get("lines") or []
            name = str(person["name"]).lower().split()[0]
            keep = set()
            for index, line in enumerate(said):
                if name in line["text"].lower():
                    keep.update(range(max(0, index - 4), min(len(said), index + 5)))
            if position == 0:  # and how the fullest one went
                keep.update(range(min(len(said), 25)))
            for index in sorted(keep)[:45]:
                lines.append(f"      [{said[index]['label']}] {_clip(said[index]['text'], 160)}")
        if talks:
            lines.append("    (These are conversations this person took part in or was named in. Speakers who were "
                         "never named appear as \"Speaker N\"; one of them may be this person.)")
    return _one("\n".join(lines))


async def conversations_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a conversation search query.")
    try:
        rows, meant = await asyncio.gather(
            store.query("conversations:search", text=query, limit=10),
            recall.find(query, limit=5, kind="conversation", timeout=2.0))
    except StoreError as error:
        return _one(f"Could not search conversations: {error}")
    if not rows and not meant:
        return _one("No matching conversation lines were found.")
    found = [f"- From the conversation \"{hit['title']}\": {_clip(hit['text'], 500)}" for hit in meant]
    return _one("\n".join(found + [f"- [{r['label']}] {_clip(r['text'])}" for r in rows[:12]]))


async def recent_conversations_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del args
    try:
        rows = await store.query("conversations:digest", limit=6)
    except StoreError as error:
        return _one(f"Could not read conversations: {error}")
    if not rows:
        return _one("No recent conversations were found.")
    lines = []
    for row in rows:
        started = datetime.fromtimestamp(row["startedAt"] / 1000).strftime("%a %d %b %H:%M")
        summary = _clip(row.get("summary") or "", 300)
        lines.append(f"- {row.get('title') or 'In progress'} ({started})" + (f": {summary}" if summary else ""))
    return _one("\n".join(lines))


async def memory_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a memory search query.")
    try:
        rows, meant = await asyncio.gather(
            store.query("memories:search", text=query, limit=15),
            recall.find(query, limit=10, kind="fact", timeout=2.0))
    except StoreError as error:
        return _one(f"Could not search memories: {error}")
    facts = list(dict.fromkeys([hit["text"] for hit in meant] + [m["text"] for m in rows]))  # by meaning, then by word
    if not facts:
        return _one("No memories matched that query.")
    return _one("\n".join(f"- {_clip(fact)}" for fact in facts[:20]))


async def notion_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    if not notion.configured():
        return _one("Notion is not connected.")
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a Notion search query.")
    try:
        pages = await notion.search(query, strict=True)
    except RuntimeError as error:
        return _one(str(error))
    if not pages:
        return _one("No matching Notion pages were found.")
    lines = []
    for page in pages[:6]:
        body = _clip(page.get("text") or "", 220)
        lines.append(f"- {page['title']}: {body}" if body else f"- {page['title']}")
    return _one("\n".join(lines))


async def docs_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a docs search query.")
    if not google.can_read_docs():
        return _one("Google Docs is not connected.")
    try:
        docs = await google.docs(query, limit=3, strict=True)
    except RuntimeError as error:
        return _one(str(error))
    if not docs:
        return _one("No matching Google Docs were found.")
    lines = []
    for doc in docs:
        text = str(doc.get("text") or "")
        extra = " (excerpt truncated)" if len(text) >= 2500 else ""
        lines.append(f"- {doc.get('title') or 'Untitled'}{extra}: {_clip(text, 220)}")
    return _one("\n".join(lines))


async def research_results_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    topic = str(args.get("topic") or "").strip().lower()
    try:
        rows = await store.query("research:list")
    except StoreError as error:
        return _one(f"Could not read research results: {error}")
    if topic:
        wanted = _word_set(topic)
        rows = [row for row in rows if wanted & _word_set(str(row.get("topic") or ""))]
    if not rows:
        return _one("No saved research results matched.")
    lines = []
    for row in rows[:5]:
        status = row.get("status") or "unknown"
        short = _clip(row.get("short") or "", 400)
        line = f"- {row.get('topic')}: {status}"
        if short:
            line += f". Short version: {short}"
        if row.get("report"):
            line += f"\n  Full report: {_clip(row['report'], 1500)}"
        lines.append(line)
    return _one("\n".join(lines))


async def todo_add_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "").strip().rstrip(".")
    if not text:
        return _one("Please provide the to-do text.")
    return await _act(store, {"action": "note", "what": text, "when": str(args.get("when") or "")})


async def todo_complete_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "").strip()
    if not text:
        return _one("Please provide the to-do to complete.")
    return await _act(store, {"action": "done", "what": text})


async def todo_remove_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "").strip()
    if not text:
        return _one("Please provide the to-do to remove.")
    return await _act(store, {"action": "drop", "what": text})


async def calendar_create_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    title = str(args.get("title") or "").strip().rstrip(".")
    when = str(args.get("when") or "").strip()
    if not title or not when:
        return _one("Please provide both title and when.")
    # Guests are invited by email. A name is looked up in the owner's contacts and mail; one
    # that cannot be found is left off and said so, never guessed.
    emails, missing = [], []
    for guest in args.get("guests") or []:
        guest = str(guest).strip()
        if not guest:
            continue
        email = guest if "@" in guest else await google.email_of(guest)
        (emails if email else missing).append(email or guest)
    if (emails or missing) and not google.can_book():
        return _one("Google Calendar is not connected, so no invitation can be sent.")
    result = await _act(store, {
        "action": "book", "what": title, "when": when, "guests": emails,
        "minutes": int(args.get("minutes") or 30), "where": str(args.get("where") or "").strip(),
    })
    note = ""
    if emails:
        note += f" Invitation sent to {', '.join(emails)}."
    if missing:
        note += (f" No email address was found for {', '.join(missing)}, so they were not invited: "
                 "ask the owner for it and then invite them.")
    if note:
        result.text += note
        for item in result.done:
            if item.get("kind") == "event":
                item["kind"], item["text"] = "said", f"{actions_confirmation([item])} {item['text']}.{note}"
    return result


async def calendar_move_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    title = str(args.get("title") or "").strip()
    when = str(args.get("when") or "").strip()
    if not title or not when:
        return _one("Please provide both title and when.")
    return await _act(store, {"action": "move", "what": title, "when": when})


async def calendar_cancel_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    title = str(args.get("title") or "").strip()
    if not title:
        return _one("Please provide the calendar event title.")
    return await _act(store, {"action": "cancel", "what": title})


async def note_save_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    text = str(args.get("text") or "").strip().rstrip(".")
    if not text:
        return _one("Please provide the note text.")
    return await _act(store, {"action": "note", "what": text})


async def research_start_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    question = str(args.get("question") or "").strip()
    if not question:
        return _one("Please provide the research question.")
    # Research runs in the background and is announced later, which is the wrong answer to a
    # simple question. It only starts when the owner asked for it in so many words.
    if not _RESEARCH.search(heard.get()):
        return _one("Answer the owner's question yourself, now and briefly, from what you know or from the other "
                    "tools. Do not mention research, searching or this tool in your answer.")
    # The owner's own people, meetings and conversations are in Wingman, not on the web.
    asked = f"{heard.get()} {question}"
    try:
        names = {str(p["name"]).lower().split()[0] for p in await store.query("people:list")
                 if not p.get("isOwner") and len(str(p["name"]).split()[0]) >= 3}
    except StoreError:
        names = set()
    if _OWN_LIFE.search(asked) or names & set(re.findall(r"[a-z]+", asked.lower())):
        return _one("Not a web question: this is about the owner's own people, meetings or conversations. Look it "
                    "up with people_lookup, recent_conversations, conversations_search, calendar_events or "
                    "memory_search, then answer. Do not mention research.")
    return await _act(store, {"action": "research", "what": question})


async def slack_import_todos_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del args
    if not slack.configured():
        return _one("Slack is not connected.")
    try:
        added = _clean_done(await slack_todos(store, fresh_only=False, strict=True))
    except Exception as error:  # noqa: BLE001
        return _one(f"Slack import failed: {error}")
    if not added:
        return ToolResult(text="No new Slack to-dos were added.", done=[])
    names = "; ".join(item["text"] for item in added[:12])  # every one, so the reply can name them all
    more = "" if len(added) <= 12 else f"; and {len(added) - 12} more"
    return ToolResult(text=f"Added {len(added)} Slack to-dos: {names}{more}.", done=added)


# --- Messages: drafted first, sent only on the owner's yes ---------------------------------------

heard: contextvars.ContextVar[str] = contextvars.ContextVar("heard", default="")  # the owner's current words
_pending = users.Scoped(dict)  # the one message waiting for a yes, per account
_RESEARCH = re.compile(r"\b(research|look into|look up|find out|dig into|investigate|deep dive|"
                       r"search (the web|online|the internet)|google)\b", re.I)
_OWN_LIFE = re.compile(
    r"\b(my|our|we|i)\b[^.?!]{0,60}\b(meetings?|conversations?|chats?|calls?|calendar|schedule|promis\w*|to-?dos?|"
    r"tasks?|said|talked|spoke|discussed|met|agreed|notes?)\b|\b(who is|who's|who was)\b", re.I)
_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|send( it| that)?|go ahead|do it|please do|okay|ok|confirm(ed)?)\b", re.I)
_NO = re.compile(r"\b(no|nope|don't|do not|cancel|wait|stop|hold on|not yet|change)\b", re.I)


async def email_search_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    query = str(args.get("query") or "").strip()
    if not query:
        return _one("Please provide a mail search query.")
    try:
        rows = await google.mail_search(query, limit=8)
    except RuntimeError as error:
        return _one(str(error))
    if not rows:
        return _one("No mail matched that search.")
    return _one("\n".join(
        f"- From {row['from']} on {row['date'][:16]}: {row['subject']}. {_clip(row['text'], 200)}" for row in rows))


async def message_draft_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store
    via = "email" if str(args.get("via") or "slack").lower().startswith("e") else "slack"
    to, text = str(args.get("to") or "").strip(), str(args.get("text") or "").strip()
    if not to or not text:
        return _one("Please provide who it is to and the message text.")
    name = to
    if via == "slack":
        if not slack.configured():
            return _one("Slack is not connected.")
        wanted = to.lower()
        people = await slack._people()
        match = next((p for p in people if p["name"].lower() == wanted or p["handle"].lower() == wanted), None) or next(
            (p for p in people if wanted in p["name"].lower() or p["name"].lower().split(" ")[0] == wanted.split(" ")[0]), None)
        if match is None:
            return _one(f"Nobody called {to} was found in the owner's Slack.")
        name = match["name"]
    else:
        if "@" not in to:
            return _one("For email, give the full address. Find it with email_search or ask the owner.")
        if not google.can_send_mail():
            return _one("Gmail is not connected for sending. The owner needs to reconnect Google in the app to allow mail.")
    _pending.clear()
    _pending.update(via=via, to=to, name=name, text=text, at=datetime.now().timestamp(), asked=heard.get(),
                    subject=str(args.get("subject") or "").strip() or "Following up")
    return _one(f"Drafted, NOT sent. To {name} by {via}: \"{text}\". Read it to the owner and ask whether to send it. "
                "Only call message_send after they say yes.")


async def message_send_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del store, args
    if not _pending or datetime.now().timestamp() - _pending.get("at", 0) > 300:
        _pending.clear()
        return _one("There is no drafted message waiting. Draft one first with message_draft.")
    said = heard.get()
    if said == _pending.get("asked"):
        # Still the message that asked for the draft: the owner has not heard it yet.
        return _one("Not sent: read the draft to the owner and wait for their yes in a new message.")
    if not _YES.search(said) or _NO.search(said):
        return _one("Not sent: the owner has not clearly said yes to this draft. Ask them.")
    draft = dict(_pending.items())
    try:
        if draft["via"] == "slack":
            name = await slack.send(draft["name"], draft["text"])
        else:
            await google.mail_send(draft["to"], draft["subject"], draft["text"])
            name = draft["to"]
    except Exception as error:  # noqa: BLE001
        return ToolResult(text=f"Not sent: {error}", done=[
            {"id": "failed", "kind": "failed", "text": f"I couldn't send it: {error}", "due": None, "dueText": None}])
    _pending.clear()
    line = f"Sent to {name} on Slack." if draft["via"] == "slack" else f"Sent to {name} by email."
    return ToolResult(text=line, done=[{"id": "sent", "kind": "said", "text": line, "due": None, "dueText": None}])


async def daily_debrief_tool(store: Store, args: dict[str, Any]) -> ToolResult:
    del args
    from wingman import daily  # here, to keep this module's imports light
    summary = await daily.debrief(store)
    return _one(summary["spoken"] + ("\n" + "\n".join(f"- {point}" for point in summary["points"]) if summary["points"] else ""))


def registry() -> dict[str, Tool]:
    return {
        "email_search": Tool("email_search", "Search the owner's Gmail with Gmail search syntax (from:, to:, subject:, is:unread, newer_than:3d). Returns sender, date, subject and opening lines.",
                             _params(["query"], query={"type": "string"}), email_search_tool),
        "message_draft": Tool("message_draft", "Draft a message for the owner to approve. Nothing is sent. Use for any request to message, tell, reply to or email someone.", _params(
            ["to", "text"], to={"type": "string", "description": "A person's name for Slack, or a full email address for email."},
            text={"type": "string", "description": "The message, written as the owner, short and natural."},
            via={"type": "string", "enum": ["slack", "email"]}, subject={"type": "string", "description": "Email subject, for email only."}),
            message_draft_tool),
        "message_send": Tool("message_send", "Send the drafted message. Only after the owner has heard the draft and said yes in their latest message.",
                             _params(), message_send_tool),
        "daily_debrief": Tool("daily_debrief", "Today summed up: what was discussed, what was promised, what was finished, what is open and what tomorrow holds. Use when asked for a debrief or how the day went.",
                              _params(), daily_debrief_tool),
        "slack_search": Tool("slack_search", "Search the owner's Slack messages by keyword: who said what, and where.",
                              _params(["query"], query={"type": "string"}), slack_search_tool),
        "slack_action_items": Tool("slack_action_items", "Read (without changing anything) the last few days of Slack messages sent to the owner, mentioning them, or written by them. Use to answer what is waiting for them in Slack.",
                                    _params(), slack_action_items_tool),
        "calendar_events": Tool("calendar_events", "Read the owner's upcoming calendar events for the next N days (default 3).",
                                _params(required=[], days={"type": "integer", "minimum": 1, "maximum": 30}),
                                calendar_events_tool),
        "todo_list": Tool("todo_list", "Read the owner's open to-do list.", _params(), todo_list_tool),
        "promises_list": Tool("promises_list", "Read open promises between the owner and others.",
                               _params(), promises_list_tool),
        "people_lookup": Tool("people_lookup", "Look up a person the owner knows: who they are, the conversations the owner had with them and what those were about, what was said around their name, and what is owed either way.",
                               _params(["name"], name={"type": "string"}), people_lookup_tool),
        "conversations_search": Tool("conversations_search", "Search the words spoken in the owner's past conversations by keyword; returns matching lines with who said them.",
                                      _params(["query"], query={"type": "string"}), conversations_search_tool),
        "recent_conversations": Tool("recent_conversations", "List the owner's most recent conversations with their titles, times and summaries.",
                                      _params(), recent_conversations_tool),
        "memory_search": Tool("memory_search", "Search facts known about the owner (work, projects, people, preferences, plans) by keyword.",
                              _params(["query"], query={"type": "string"}), memory_search_tool),
        "notion_search": Tool("notion_search", "Search the owner's connected Notion pages.",
                              _params(["query"], query={"type": "string"}), notion_search_tool),
        "docs_search": Tool("docs_search", "Search the owner's Google Docs.",
                            _params(["query"], query={"type": "string"}), docs_search_tool),
        "research_results": Tool("research_results", "Read research Wingman has already done: status, short version and full report. Optionally filter by topic words.",
                                  _params(required=[], topic={"type": "string"}), research_results_tool),
        "todo_add": Tool("todo_add", "Add one to-do. With a time it becomes a reminder that is spoken when due. The same to-do reworded is merged, not duplicated.", _params(
            ["text"], text={"type": "string"}, when={"type": "string", "description": "Local time as YYYY-MM-DDTHH:MM, worked out from now. Leave empty if no time was given."}), todo_add_tool),
        "todo_complete": Tool("todo_complete", "Tick off a to-do, reminder or promise the owner has dealt with. Give its wording from the list.",
                              _params(["text"], text={"type": "string"}), todo_complete_tool),
        "todo_remove": Tool("todo_remove", "Delete a to-do, reminder or promise the owner no longer wants. Give its wording from the list.",
                            _params(["text"], text={"type": "string"}), todo_remove_tool),
        "calendar_create": Tool("calendar_create", "Put an event on the owner's Google calendar and, when guests are given, send them the invitation. Use for 'send X an invite', 'set up a meeting with X'. Check calendar_events first for a clash.", _params(
            ["title", "when"], title={"type": "string"},
            guests={"type": "array", "items": {"type": "string"}, "description": "People to invite: a name the owner used, or an email address if one was said."}, when={"type": "string", "description": "Local time as YYYY-MM-DDTHH:MM, worked out from now. Leave empty if no time was given."},
            minutes={"type": "integer", "minimum": 5, "maximum": 600}, where={"type": "string"}),
            calendar_create_tool),
        "calendar_move": Tool("calendar_move", "Move an existing calendar event to a new start time, keeping its length. Give the event's title or who it is with.", _params(
            ["title", "when"], title={"type": "string"}, when={"type": "string", "description": "Local time as YYYY-MM-DDTHH:MM, worked out from now. Leave empty if no time was given."}), calendar_move_tool),
        "calendar_cancel": Tool("calendar_cancel", "Cancel a calendar event by title.", _params(
            ["title"], title={"type": "string"}), calendar_cancel_tool),
        "note_save": Tool("note_save", "Keep a note for the owner (also written to their Notion when connected). Not for things to do: use todo_add for those.",
                          _params(["text"], text={"type": "string"}), note_save_tool),
        "research_start": Tool("research_start", "Start web research in the background. ONLY when the owner asks for research in so many words (research, look into, look up, find out, dig into). It takes a minute or two and is announced when ready. Never for a simple question: answer those directly.", _params(
            ["question"], question={"type": "string"}), research_start_tool),
        "slack_import_todos": Tool("slack_import_todos", "Read the owner's recent Slack messages, work out what they need to do, and add those to the to-do list. Returns the to-dos it added. Use this when asked to pick up, pull or import tasks from Slack.",
                                    _params(), slack_import_todos_tool),
    }


# Tools that change something and report it themselves: no second look by the model is needed.
ACTIONS = {"message_draft", "message_send", "todo_add", "todo_complete", "todo_remove", "calendar_create", "calendar_move", "calendar_cancel",
           "note_save", "research_start", "slack_import_todos"}


# Where each reading tool looks, for saying so aloud.
_WHERE = {
    "slack_search": "Slack", "slack_action_items": "your recent Slack messages", "calendar_events": "your calendar",
    "todo_list": "your to-do list", "promises_list": "your promises", "people_lookup": "the people you know",
    "conversations_search": "your conversations", "recent_conversations": "your recent conversations",
    "memory_search": "what I know about you", "notion_search": "Notion", "docs_search": "your documents",
    "research_results": "the research", "email_search": "your email", "daily_debrief": "today",
}


def _topic(arguments: str) -> str:
    """The thing being looked for, as a few plain words that can be said aloud."""
    try:
        args = json.loads(arguments or "{}")
    except ValueError:
        return ""
    value = next((str(args[key]) for key in ("query", "name", "topic") if isinstance(args, dict) and args.get(key)), "")
    words = []
    for word in re.sub(r"[^\w\s:'-]", " ", value).split():
        # Search operators and code-like tokens ("from:me", "eleven_v4") are not for speaking.
        if ":" in word or "_" in word or word.lower() in ("from", "to", "in", "about", "and", "or", "the", "a", "of", "for"):
            continue
        words.append(word)
    return " ".join(words[:4])


def _listed(places: list[str]) -> str:
    if len(places) == 1:
        return places[0]
    if len(places) == 2:
        return f"{places[0]} and {places[1]}"
    return f"{places[0]}, {places[1]} and more"


def filler(calls: list[tuple[str, str]]) -> str | None:
    """One short spoken line saying what Wingman is doing right now, from the tools it just
    reached for: "Searching Slack for voice samples.", "Checking your calendar and your to-do
    list.", "Looking up Akshat." None when it is only carrying out a quick action."""
    names = [name for name, _ in calls]
    if "slack_import_todos" in names:
        return "Going through Slack for your tasks."
    reading = [(name, arguments) for name, arguments in calls if name in _WHERE]
    if not reading:
        return None
    who = next((_topic(arguments) for name, arguments in reading if name == "people_lookup"), "")
    generic = {"today", "recent", "meeting", "meetings", "people", "everyone", "anyone", "me", "my", "who", "yesterday"}
    if who and len(who.split()) <= 3 and not set(who.lower().split()) & generic:  # an actual name
        return f"Looking up {who}."
    if all(name == "research_results" for name, _ in reading):
        return "Pulling up the research."
    places = list(dict.fromkeys(_WHERE[name] for name, _ in reading))
    topic = next((t for t in (_topic(arguments) for name, arguments in reading if "search" in name) if t), "")
    if topic and places == ["what I know about you"]:
        return f"Checking what I know about {topic}."
    if topic:
        searched = list(dict.fromkeys(_WHERE[name] for name, _ in reading if "search" in name))
        outside = [place for place in searched if place != "what I know about you"]  # reads badly in a list
        return f"Searching {_listed(outside or searched)} for {topic}."
    return f"Checking {_listed(places)}."


def specs() -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.schema,
        },
    } for tool in registry().values()]


async def run_tool(store: Store, name: str, arguments: str) -> ToolResult:
    tools = registry()
    tool = tools.get(name)
    if tool is None:
        return _one(f"Unknown tool: {name}")
    try:
        args = json.loads(arguments or "{}") if arguments else {}
        if not isinstance(args, dict):
            return _one(f"{name} failed: arguments must be a JSON object.")
    except ValueError as error:
        return _one(f"{name} failed: invalid JSON arguments ({error}).")
    try:
        result = await tool.run(store, args)
    except Exception as error:  # noqa: BLE001
        return _one(f"{name} failed: {error}")
    return result


def describe_done(done: list[dict]) -> str:
    if not done:
        return "Nothing changed."
    failures = [item["text"] for item in done if item.get("kind") == "failed" and item.get("text")]
    if failures:
        return " ".join(failures)
    said = [item["text"] for item in done if item.get("kind") == "said" and item.get("text")]
    if said:
        return " ".join(said)
    if all(item.get("kind") == "research" for item in done):
        topics = "; ".join(item["text"] for item in done if item.get("text"))
        return f"Started research: {topics}."
    names = [item["text"] for item in done if item.get("text")]
    if not names:
        return "Done."
    head = "; ".join(names[:4])
    tail = "" if len(names) <= 4 else f"; and {len(names) - 4} more"
    return f"Done: {head}{tail}."
