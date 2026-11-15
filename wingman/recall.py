"""Finding things by what they mean, not by the words they happen to use.

Wingman's own search matches words, so a conversation about growing plants never found the
fact that its owner keeps forty houseplants. Supermemory holds a copy of every fact and every
finished conversation and searches them by meaning. Convex stays the record of truth; this is
only how things are found again. Each account has its own space there, and when Supermemory
is not set up or does not answer in time, callers fall back to the word search they had.
"""

import asyncio
import hashlib
import os

import httpx

from wingman import users

BASE = "https://api.supermemory.ai"
_client: httpx.AsyncClient | None = None
_running: set[asyncio.Task] = set()


def configured() -> bool:
    return bool(os.environ.get("SUPERMEMORY_API_KEY"))


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE, timeout=30, headers={
            "Authorization": f"Bearer {os.environ['SUPERMEMORY_API_KEY']}", "Content-Type": "application/json"})
    return _client


def space() -> str:
    """This account's own space. Nothing is ever searched across spaces.

    Two servers with separate databases can share one Supermemory key; each then sets its own
    SUPERMEMORY_SPACE, or their first owners (both called "owner") would share a space."""
    return (os.environ.get("SUPERMEMORY_SPACE") or "wingman") + "_" + users.user()


def fact_id(text: str) -> str:
    return "fact_" + hashlib.sha1(text.strip().lower().encode()).hexdigest()[:24]


async def keep(items: list[dict]) -> int:
    """Store documents ({"content", "id", "metadata"}), in batches. Returns how many were taken."""
    if not configured() or not items:
        return 0
    taken = 0
    for start in range(0, len(items), 200):
        batch = [{"content": item["content"][:20000], "id": item["id"], "metadata": item.get("metadata") or {}}
                 for item in items[start:start + 200] if item.get("content", "").strip()]
        try:
            # Plain indexing: the facts are already worked out, they only need to be findable.
            answer = await _http().post(f"/ns/{space()}/document/batch", json={"documents": batch, "taskType": "superrag"})
            if answer.status_code == 200:
                taken += int(answer.json().get("count") or 0)
            else:
                print(f"recall: keep refused ({answer.status_code}) {answer.text[:160]}", flush=True)
        except httpx.HTTPError as error:
            print(f"recall: keep failed: {type(error).__name__}", flush=True)
    return taken


def later(coroutine):
    """Run a keep or a drop in the background: remembering must never slow an answer down."""
    task = asyncio.create_task(coroutine)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def keep_facts(source: str, facts: list[str]) -> int:
    return await keep([{"content": fact, "id": fact_id(fact), "metadata": {"type": "fact", "source": source}}
                       for fact in facts if fact.strip()])


async def keep_conversation(ident: str, title: str, summary: str, points: list[str], lines: str, day: str) -> int:
    content = (f"Conversation: {title} ({day}).\nSummary: {summary}\n"
               + ("Worth keeping: " + " ".join(points) + "\n" if points else "") + lines)
    return await keep([{"content": content, "id": f"conv_{ident}",
                        "metadata": {"type": "conversation", "title": title, "day": day}}])


async def find(query: str, limit: int = 8, kind: str | None = None, least: float = 0.6,
               timeout: float = 1.5) -> list[dict]:
    """What is kept that bears on the query: [{"text", "kind", "title", "source", "similarity"}],
    best first. Empty when nothing clears the bar, and also when the search could not be done."""
    if not configured() or not query.strip():
        return []
    body = {"query": query[:600], "searchMode": "chunks", "limit": limit, "threshold": least}
    if kind:
        body["filter"] = {"field": "type", "operator": "eq", "value": kind}
    try:
        answer = await asyncio.wait_for(_http().post(f"/ns/{space()}/search", json=body), timeout)
        if answer.status_code != 200:
            return []
        results = answer.json().get("results") or []
    except (httpx.HTTPError, asyncio.TimeoutError, TimeoutError, ValueError):
        return []
    out = []
    for item in results:
        text = (item.get("chunk") or item.get("memory") or "").strip()
        meta = item.get("metadata") or {}
        if text:
            out.append({"text": text, "kind": meta.get("type") or "", "title": meta.get("title") or "",
                        "source": meta.get("source") or "", "similarity": float(item.get("similarity") or 0)})
    return out


async def drop(ids: list[str]):
    if not configured() or not ids:
        return
    try:
        await _http().request("DELETE", f"/ns/{space()}/document", json={"ids": ids[:100]})
    except httpx.HTTPError:
        pass


async def clear():
    """Forget everything kept for this account."""
    if not configured():
        return
    try:
        await _http().request("DELETE", f"/ns/{space()}")
    except httpx.HTTPError:
        pass
