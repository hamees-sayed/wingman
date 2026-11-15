"""The owner's Notion: pages they have shared with Wingman.

Wingman reads those pages when the owner is reaching for something or planning, and keeps
its own notes on a page called "Wingman notes". It can only see what the owner shares with
the integration inside Notion (page menu, Connections).
"""

import json
import os
import time
from urllib.parse import urlencode

import httpx

from wingman import config

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
NOTES_PAGE = "Wingman notes"

_about: tuple[float, dict] | None = None
_notes_page: str | None = None


# A person who connects through the "Connect Notion" button gets their own token, kept here.
# Without one, the server falls back to the owner's internal integration secret, if set.
TOKEN = config.DATA_DIR / "notion-token.json"
REDIRECT = os.environ.get("NOTION_REDIRECT_URI", "http://localhost:8787/oauth/notion/callback")


def can_sign_in() -> bool:
    """Is the public integration set up, so anyone can connect their own Notion."""
    return bool(os.environ.get("NOTION_CLIENT_ID") and os.environ.get("NOTION_CLIENT_SECRET"))


def _token() -> str | None:
    if TOKEN.exists():
        try:
            return json.loads(TOKEN.read_text()).get("access_token")
        except ValueError:
            return None
    return os.environ.get("NOTION_TOKEN") or None


def configured() -> bool:
    return _token() is not None


def sign_in_url() -> str:
    return "https://api.notion.com/v1/oauth/authorize?" + urlencode({
        "client_id": os.environ["NOTION_CLIENT_ID"], "response_type": "code",
        "owner": "user", "redirect_uri": REDIRECT,
    })


async def finish_sign_in(code: str) -> str:
    """Trade Notion's code for this person's token."""
    global _about, _notes_page
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{API}/oauth/token",
            auth=(os.environ["NOTION_CLIENT_ID"], os.environ["NOTION_CLIENT_SECRET"]),
            json={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Notion refused the sign-in: {response.text[:300]}")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps(response.json()))
    TOKEN.chmod(0o600)
    _about = _notes_page = None
    return response.json().get("workspace_name") or "your Notion"


def disconnect():
    global _about, _notes_page
    TOKEN.unlink(missing_ok=True)
    _about = _notes_page = None


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Notion-Version": VERSION}


async def _call(method: str, path: str, body: dict | None = None, timeout: float = 10) -> dict | None:
    if not configured():
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{API}{path}", json=body, headers=_headers())
        return response.json() if response.status_code == 200 else None
    except httpx.HTTPError:
        return None


def _title(item: dict) -> str:
    for prop in (item.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "".join(part.get("plain_text", "") for part in item.get("title", []) or [])


async def about() -> dict:
    """Whether Notion is connected, to which workspace, and how many pages it can see."""
    global _about
    if _about and time.time() - _about[0] < 20:
        return _about[1]
    state = {"configured": configured(), "connected": False, "workspace": None, "pages": 0,
             "signIn": can_sign_in(), "own": TOKEN.exists()}
    me = await _call("GET", "/users/me")
    if me:
        state["connected"] = True
        state["workspace"] = (me.get("bot") or {}).get("workspace_name")
        found = await _call("POST", "/search", {"page_size": 50})
        state["pages"] = len((found or {}).get("results", []))
    _about = (time.time(), state)
    return state


async def _text(page_id: str, limit: int = 1800) -> str:
    """The words on a page, top level only."""
    data = await _call("GET", f"/blocks/{page_id}/children?page_size=60")
    lines = []
    for block in (data or {}).get("results", []):
        rich = (block.get(block.get("type"), {}) or {}).get("rich_text") or []
        line = "".join(part.get("plain_text", "") for part in rich).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)[:limit]


async def search(query: str, pages: int = 3, timeout: float = 6) -> list[dict]:
    """Pages matching the words, each with its title and text."""
    found = await _call("POST", "/search", {"query": query, "page_size": pages,
                                             "filter": {"property": "object", "value": "page"}}, timeout)
    out = []
    for item in (found or {}).get("results", []):
        title = _title(item) or "Untitled"
        if title == NOTES_PAGE:
            continue
        out.append({"title": title, "text": await _text(item["id"]), "url": item.get("url", "")})
    return out


async def save_note(text: str) -> bool:
    """Adds a line to the "Wingman notes" page, creating it under a shared page if needed."""
    global _notes_page
    if _notes_page is None:
        found = await _call("POST", "/search", {"query": NOTES_PAGE, "page_size": 5,
                                                 "filter": {"property": "object", "value": "page"}})
        match = next((i for i in (found or {}).get("results", []) if _title(i) == NOTES_PAGE), None)
        if match:
            _notes_page = match["id"]
        else:
            anywhere = await _call("POST", "/search", {"page_size": 1,
                                                        "filter": {"property": "object", "value": "page"}})
            parent = next(iter((anywhere or {}).get("results", [])), None)
            if parent is None:
                return False  # nothing is shared with Wingman yet, so there is nowhere to write
            made = await _call("POST", "/pages", {
                "parent": {"page_id": parent["id"]},
                "properties": {"title": {"title": [{"text": {"content": NOTES_PAGE}}]}},
            })
            if not made:
                return False
            _notes_page = made["id"]
    stamp = time.strftime("%a %d %b, %H:%M")
    added = await _call("PATCH", f"/blocks/{_notes_page}/children", {"children": [{
        "object": "block", "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": f"{stamp}: {text}"[:1900]}}]},
    }]})
    if added is None:
        _notes_page = None  # the page may have been deleted; look again next time
    return added is not None
