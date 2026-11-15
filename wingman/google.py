"""The owner's Google account: calendar, contacts and mail, read-only.

Sign-in uses an OAuth client the owner creates in their own Google Cloud console; its ID and
secret go in .env as GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET. Google only redirects back to
localhost or a public domain, so the sign-in is done in a browser on the machine running the
server: http://localhost:8787/oauth/google/start
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from wingman import config

TOKEN = config.DATA_DIR / "google-token.json"
REDIRECT = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8787/oauth/google/callback")
# Calendar and contacts only. Mail is a "restricted" scope that needs a paid audit, so it
# is left out until Wingman is ready for that.
WRITE = "https://www.googleapis.com/auth/calendar.events"
DOCS = "https://www.googleapis.com/auth/drive.readonly"
SCOPES = [
    WRITE,  # read events, and add one when the owner asks for it
    DOCS,  # find and read the owner's Google Docs
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def connected() -> bool:
    return TOKEN.exists()


def account() -> str | None:
    if not TOKEN.exists():
        return None
    return json.loads(TOKEN.read_text()).get("email")


def can_book() -> bool:
    """Has the owner granted permission to add events, not just read them."""
    if not TOKEN.exists():
        return False
    return WRITE in json.loads(TOKEN.read_text()).get("scope", "")


def can_read_docs() -> bool:
    if not TOKEN.exists():
        return False
    return DOCS in json.loads(TOKEN.read_text()).get("scope", "")


async def docs(query: str, limit: int = 2, timeout: float = 8) -> list[dict]:
    """Google Docs whose text mentions the words, each with its title and opening text."""
    token = await _access_token() if can_read_docs() else None
    words = [w for w in query.replace("'", " ").split() if len(w) >= 4][:4]
    if token is None or not words:
        return []
    wanted = " and ".join(f"fullText contains '{w}'" for w in words[:2])
    headers = {"Authorization": f"Bearer {token}"}
    out = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            found = await client.get("https://www.googleapis.com/drive/v3/files", headers=headers, params={
                "q": f"mimeType='application/vnd.google-apps.document' and trashed=false and ({wanted})",
                "orderBy": "modifiedTime desc", "pageSize": str(limit), "fields": "files(id,name)",
            })
            for item in (found.json().get("files", []) if found.status_code == 200 else []):
                text = await client.get(f"https://www.googleapis.com/drive/v3/files/{item['id']}/export",
                                        headers=headers, params={"mimeType": "text/plain"})
                if text.status_code == 200:
                    out.append({"title": item["name"], "text": text.text.strip()[:2500]})
    except httpx.HTTPError:
        return out
    return out


async def recent_docs(limit: int = 6, timeout: float = 15) -> list[dict]:
    """The Google Docs the owner touched most recently, each with its title and opening text."""
    token = await _access_token() if can_read_docs() else None
    if token is None:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    out = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            found = await client.get("https://www.googleapis.com/drive/v3/files", headers=headers, params={
                "q": "mimeType='application/vnd.google-apps.document' and trashed=false",
                "orderBy": "modifiedByMeTime desc", "pageSize": str(limit), "fields": "files(id,name)",
            })
            for item in (found.json().get("files", []) if found.status_code == 200 else []):
                text = await client.get(f"https://www.googleapis.com/drive/v3/files/{item['id']}/export",
                                        headers=headers, params={"mimeType": "text/plain"})
                if text.status_code == 200:
                    out.append({"title": item["name"], "text": text.text.strip()[:2500]})
    except httpx.HTTPError:
        return out
    return out


async def find_event(title: str, near_ms: float | None = None) -> dict | None:
    """The upcoming event the owner most likely means by these words."""
    skip = {"the", "a", "an", "my", "with", "meeting", "call", "event", "at", "on", "for", "to", "and", "of"}
    wanted = {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in skip} or set(re.findall(r"[a-z0-9]+", title.lower()))
    best, best_score = None, 0.0
    for event in await events(24 * 21):
        if not event.get("id"):
            continue  # from the phone's calendar: it can be read but not changed from here
        words = set(re.findall(r"[a-z0-9]+", event["title"].lower())) | {
            w for person in event.get("people", []) for w in re.findall(r"[a-z0-9]+", person.lower())}
        score = len(wanted & words) / max(1, len(wanted))
        if near_ms is not None:
            try:
                if abs(datetime.fromisoformat(event["start"]).timestamp() * 1000 - near_ms) < 3600_000:
                    score += 0.5
            except (ValueError, TypeError):
                pass
        if score > best_score:
            best, best_score = event, score
    return best if best_score >= 0.5 else None


async def _change(method: str, event_id: str, body: dict | None = None) -> bool:
    token = await _access_token()
    if token is None:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method, f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return False
    _cache.pop("events", None)
    return response.status_code in (200, 204)


async def move_event(event: dict, start_ms: float) -> bool:
    """Moves an event to a new start, keeping its length."""
    try:
        length = datetime.fromisoformat(event["end"]) - datetime.fromisoformat(event["start"])
    except (ValueError, TypeError):
        length = timedelta(minutes=30)
    start = datetime.fromtimestamp(start_ms / 1000).astimezone()
    return await _change("PATCH", event["id"], {"start": {"dateTime": start.isoformat()},
                                                "end": {"dateTime": (start + length).isoformat()}})


async def cancel_event(event: dict) -> bool:
    return await _change("DELETE", event["id"])


async def create_event(title: str, start_ms: float, minutes: int = 30, where: str = "") -> dict | None:
    """Adds an event to the owner's main calendar. Returns it, or None if Google refused."""
    token = await _access_token()
    if token is None:
        return None
    start = datetime.fromtimestamp(start_ms / 1000).astimezone()
    end = start + timedelta(minutes=minutes)
    body = {"summary": title[:1].upper() + title[1:],
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
            "description": "Added by Wingman at your request."}
    if where:
        body["location"] = where
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                                         json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    if response.status_code not in (200, 201):
        return None
    _cache.pop("events", None)
    return {"title": body["summary"], "start": start.isoformat(), "end": end.isoformat()}


async def clashes(start_ms: float, minutes: int = 30) -> list[dict]:
    """What is already on the calendar during a proposed time."""
    end_ms, out = start_ms + minutes * 60_000, []
    for event in await events(24 * 14):
        try:
            a = datetime.fromisoformat(event["start"]).timestamp() * 1000
            b = datetime.fromisoformat(event["end"]).timestamp() * 1000
        except (ValueError, TypeError):
            continue
        if "T" in event["start"] and a < end_ms and b > start_ms:
            out.append(event)
    return out


def sign_in_url() -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })


async def finish_sign_in(code: str, redirect: str | None = None) -> str:
    """Trade the code Google sent back for tokens, and keep them on this machine only.

    A code from the in-app "Continue with Google" button comes with no redirect address, so
    the app passes redirect="" for those; the browser flow uses the localhost address.
    """
    redirect = REDIRECT if redirect is None else redirect
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        })
        if response.status_code != 200:
            raise RuntimeError(f"Google refused the sign-in: {response.text[:300]}")
        tokens = response.json()
        tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600) - 60
        who = await client.get("https://www.googleapis.com/oauth2/v2/userinfo",
                               headers={"Authorization": f"Bearer {tokens['access_token']}"})
        tokens["email"] = who.json().get("email") if who.status_code == 200 else None
    if "refresh_token" not in tokens and TOKEN.exists():  # Google only sends it the first time
        tokens["refresh_token"] = json.loads(TOKEN.read_text()).get("refresh_token")
    _cache.clear()
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps(tokens))
    TOKEN.chmod(0o600)
    return tokens.get("email") or "your Google account"


def disconnect():
    TOKEN.unlink(missing_ok=True)
    _cache.clear()


async def _access_token() -> str | None:
    if not TOKEN.exists():
        return None
    tokens = json.loads(TOKEN.read_text())
    if time.time() < tokens.get("expires_at", 0):
        return tokens["access_token"]
    if not tokens.get("refresh_token") or not configured():
        return None
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        })
    if response.status_code != 200:
        return None
    fresh = response.json()
    tokens["access_token"] = fresh["access_token"]
    tokens["expires_at"] = time.time() + fresh.get("expires_in", 3600) - 60
    TOKEN.write_text(json.dumps(tokens))
    return tokens["access_token"]


async def _get(url: str, params: dict) -> dict | None:
    token = await _access_token()
    if token is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        return response.json() if response.status_code == 200 else None
    except httpx.HTTPError:
        return None


# What the phone itself shared: its own calendar and contacts, read with the owner's
# permission. No sign-in is involved; the phone already has them.
DEVICE = config.DATA_DIR / "device.json"


def device() -> dict:
    try:
        return json.loads(DEVICE.read_text())
    except (OSError, ValueError):
        return {}


def save_device(events: list | None, people: list | None) -> dict:
    held = device()
    if events is not None:
        held["events"], held["eventsAt"] = events[:200], time.time()
    if people is not None:
        held["contacts"], held["contactsAt"] = people[:2000], time.time()
    DEVICE.parent.mkdir(parents=True, exist_ok=True)
    DEVICE.write_text(json.dumps(held))
    return {"events": len(held.get("events", [])), "contacts": len(held.get("contacts", []))}


def _device_events(hours: int) -> list[dict]:
    now, until = time.time() * 1000, (time.time() + hours * 3600) * 1000
    out = []
    for event in device().get("events", []):
        if event.get("end", 0) < now or event.get("start", 0) > until:
            continue
        out.append({
            "title": event.get("title") or "Untitled",
            "start": datetime.fromtimestamp(event["start"] / 1000).astimezone().isoformat(timespec="minutes"),
            "end": datetime.fromtimestamp(event.get("end", event["start"]) / 1000).astimezone().isoformat(timespec="minutes"),
            "people": event.get("people", [])[:8],
            "where": event.get("where", ""),
        })
    return sorted(out, key=lambda e: e["start"])


_cache: dict[str, tuple[float, list]] = {}


async def _cached(key: str, seconds: float, load) -> list:
    """Answers come from a local copy a few minutes old, so nothing waits on Google."""
    held = _cache.get(key)
    if held and time.time() - held[0] < seconds:
        return held[1]
    value = await load()
    _cache[key] = (time.time(), value)
    return value


async def events(hours: int = 48) -> list[dict]:
    """What is on the calendar from now: title, start, end, who is invited."""
    async def load():
        now = datetime.now(timezone.utc)
        data = await _get("https://www.googleapis.com/calendar/v3/calendars/primary/events", {
            "timeMin": now.isoformat(), "timeMax": (now + timedelta(hours=hours)).isoformat(),
            "singleEvents": "true", "orderBy": "startTime", "maxResults": "30",
        })
        out = []
        for item in (data or {}).get("items", []):
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
            if not start:
                continue
            out.append({
                "id": item.get("id"),
                "title": item.get("summary") or "Untitled",
                "start": start, "end": end,
                "people": [a.get("displayName") or a.get("email", "").split("@")[0]
                           for a in item.get("attendees", []) if not a.get("self")][:8],
                "where": item.get("location") or "",
            })
        return out
    if connected():
        return await _cached("events", 180, load)
    return _device_events(hours)


async def past_events(days: int = 30) -> list[dict]:
    """What was on the calendar recently: who the owner meets and what their weeks look like."""
    if not connected():
        return []
    now = datetime.now(timezone.utc)
    data = await _get("https://www.googleapis.com/calendar/v3/calendars/primary/events", {
        "timeMin": (now - timedelta(days=days)).isoformat(), "timeMax": now.isoformat(),
        "singleEvents": "true", "orderBy": "startTime", "maxResults": "60",
    })
    out = []
    for item in (data or {}).get("items", []):
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        if start:
            out.append({"title": item.get("summary") or "Untitled", "start": start,
                        "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
                        "people": [a.get("displayName") or a.get("email", "").split("@")[0]
                                   for a in item.get("attendees", []) if not a.get("self")][:8],
                        "where": item.get("location") or ""})
    return out


async def contacts() -> list[dict]:
    """Names and where they work, so a name can be supplied even if never spoken."""
    async def load():
        data = await _get("https://people.googleapis.com/v1/people/me/connections", {
            "personFields": "names,organizations", "pageSize": "400", "sortOrder": "LAST_MODIFIED_DESCENDING",
        })
        out = []
        for person in (data or {}).get("connections", []):
            name = (person.get("names") or [{}])[0].get("displayName")
            if not name:
                continue
            org = (person.get("organizations") or [{}])[0]
            about = ", ".join(part for part in (org.get("title"), org.get("name")) if part)
            out.append({"name": name, "about": about})
        return out
    if connected():
        return await _cached("contacts", 1800, load)
    return device().get("contacts", [])


def describe(items: list[dict]) -> str:
    """The calendar as plain lines for the model."""
    lines = []
    for event in items[:20]:
        try:
            start = datetime.fromisoformat(event["start"]).astimezone()
            when = start.strftime("%a %d %b %H:%M") if "T" in event["start"] else start.strftime("%a %d %b, all day")
        except ValueError:
            when = event["start"]
        people = f" with {', '.join(event['people'])}" if event["people"] else ""
        lines.append(f"- {when}: {event['title']}{people}")
    return "\n".join(lines)
