"""Wingman as a connector for other assistants (Model Context Protocol, over plain HTTP).

Claude or ChatGPT, once given Wingman's connector address, can hand over what they know
about the owner and look up what Wingman knows, with no copying between apps. The address
carries a private token, so only assistants the owner gave it to can reach it.
"""

import hashlib
import os

from wingman import actions, profile
from wingman.store import Store, StoreError

VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "remember",
        "description": (
            "Save what you know about the user into Wingman, their always-listening personal assistant. "
            "Use this when the user asks you to send, sync or share your memory with Wingman, and whenever "
            "you learn something durable about them worth keeping. Send everything you remember in one call."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "facts": {"type": "array", "items": {"type": "string"}, "description": (
                    "Standalone sentences about the user, each starting with 'You' or 'Your': work, role, projects, "
                    "people in their life, preferences, plans and dates, routines, constraints, goals. One fact each.")},
                "people": {"type": "array", "description": "Real people in the user's life.", "items": {
                    "type": "object", "properties": {"name": {"type": "string"}, "about": {
                        "type": "string", "description": "Who they are to the user, a few words."}},
                    "required": ["name"]}},
                "assistant": {"type": "string", "description": "Which assistant you are, e.g. Claude or ChatGPT."},
            },
            "required": ["facts"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Look up what Wingman knows about the user: who they are, what was said in their recent conversations, "
            "what they promised people and what is on their to-do list. Use it when the user asks about their day, "
            "their commitments, a person they met, or anything Wingman would have heard."),
        "inputSchema": {"type": "object", "properties": {"question": {
            "type": "string", "description": "What you want to know, in plain words."}}, "required": ["question"]},
    },
    {
        "name": "add_todo",
        "description": "Put something on the user's Wingman to-do list, optionally with a time to be reminded.",
        "inputSchema": {"type": "object", "properties": {
            "text": {"type": "string", "description": "The to-do, short, starting with a verb."},
            "when": {"type": "string", "description": "Local time as YYYY-MM-DDTHH:MM, if a time applies."}},
            "required": ["text"]},
    },
]


def token() -> str:
    """The private part of the connector address. It is not the app's own key."""
    return hashlib.sha256(("connector:" + os.environ.get("WINGMAN_KEY", "")).encode()).hexdigest()[:28]


def address() -> str:
    return f"{os.environ.get('PUBLIC_URL', 'http://localhost:8787').rstrip('/')}/mcp/{token()}"


async def _remember(store: Store, args: dict) -> str:
    facts = [str(f).strip() for f in args.get("facts") or [] if str(f).strip()][:200]
    source = str(args.get("assistant") or "Another assistant").strip()[:40] or "Another assistant"
    added = int(await store.mutation("memories:addMany", source=source, facts=facts)) if facts else 0
    people = 0
    for person in args.get("people") or []:
        if isinstance(person, dict) and str(person.get("name") or "").strip():
            await store.mutation("people:upsert", name=str(person["name"]).strip()[:80],
                                 about=str(person.get("about") or "").strip()[:200] or None)
            people += 1
    if added:
        profile.schedule(store, "rewrite", "")
    return (f"Saved to Wingman: {added} new facts" + (f" and {people} people" if people else "")
            + (f" ({len(facts) - added} were already known)." if len(facts) > added else "."))


async def _recall(store: Store, args: dict) -> str:
    import re
    question = str(args.get("question") or "")
    words = " ".join(w for w in re.findall(r"[A-Za-z0-9]+", question) if len(w) >= 4)[:200]
    parts = []
    about = await profile.text(store)
    if about:
        parts.append("Who they are:\n" + about)
    if words:
        memories = await store.query("memories:search", text=words, limit=12)
        if memories:
            parts.append("Facts that match:\n" + "\n".join(f"- {m['text']}" for m in memories))
        lines = await store.query("conversations:search", text=words, limit=12)
        if lines:
            parts.append("Said in their conversations:\n" + "\n".join(f"- [{l['label']}] {l['text']}" for l in lines))
    digest = await store.query("conversations:digest", limit=5)
    if digest:
        parts.append("Recent conversations:\n" + "\n".join(
            f"- {c.get('title') or 'Untitled'}: {c.get('summary') or ''}" for c in digest if c.get("title")))
    promises = await store.query("promises:open")
    if promises:
        parts.append("Open promises:\n" + "\n".join(
            f"- {'They owe ' + p['person'] if p['by'] == 'you' else p['person'] + ' owes them'}: {p['what']}" for p in promises[:20]))
    tasks = await store.query("tasks:open")
    if tasks:
        parts.append("To-do list:\n" + "\n".join(f"- {t['text']}" for t in tasks[:25]))
    return "\n\n".join(parts)[:12000] or "Wingman does not know anything about this yet."


async def _add_todo(store: Store, args: dict) -> str:
    text = str(args.get("text") or "").strip().rstrip(".")
    if not text:
        return "Nothing to add."
    due = actions.parse_when(str(args.get("when") or ""))
    await store.mutation("tasks:add", kind="reminder" if due else "note", text=text[:200], due=due)
    return f"Added to the Wingman to-do list: {text}." + (" A reminder is set." if due else "")


async def handle(store: Store, message: dict) -> dict | None:
    """One JSON-RPC message in, its reply out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None  # notifications need no answer
    def reply(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}
    if method == "initialize":
        wanted = (message.get("params") or {}).get("protocolVersion") or VERSION
        return reply({"protocolVersion": wanted, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "Wingman", "title": "Wingman", "version": "1.0.0"},
                      "instructions": ("Wingman is the user's always-listening personal assistant and second brain. "
                                       "Use remember to hand over what you know about the user, recall to ask what "
                                       "Wingman knows, add_todo to put something on their list.")})
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": TOOLS})
    if method in ("resources/list", "prompts/list"):
        return reply({method.split("/")[0]: []})
    if method == "tools/call":
        params = message.get("params") or {}
        run = {"remember": _remember, "recall": _recall, "add_todo": _add_todo}.get(params.get("name"))
        if run is None:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "Unknown tool"}}
        try:
            text, failed = await run(store, params.get("arguments") or {}), False
        except StoreError as error:
            text, failed = f"Wingman could not do that just now: {error}", True
        return reply({"content": [{"type": "text", "text": text}], "isError": failed})
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Method not found: {method}"}}
