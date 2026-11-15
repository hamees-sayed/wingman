"""The fixed front door.

The server that does the work runs wherever is closest to its owner, on a machine whose
public address changes whenever it restarts. This small service runs on a machine with an
address that never changes and does two things:

- tells the app where the working server is right now (GET /where), and is told by that
  server each time it starts (POST /where);
- passes on everything else it is asked for, so links that must not change (sign-in returns
  from Google, Slack and Notion, the connector address given to Claude or ChatGPT, the app
  download) keep working.

The live audio connection is not passed on: the app goes straight to the working server for
that, which is the whole point of having it nearby.
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
STATE = Path(os.environ.get("WINGMAN_DATA_DIR", ROOT / "data")) / "front.json"
app = FastAPI(title="Wingman front door")
_http = httpx.AsyncClient(timeout=120, follow_redirects=False)
_DROP = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}


def _key_ok(request: Request) -> bool:
    key = os.environ.get("WINGMAN_KEY", "")
    return bool(key) and (request.headers.get("x-wingman-key") == key or request.query_params.get("k") == key)


def _where() -> str:
    try:
        return json.loads(STATE.read_text()).get("url", "")
    except (OSError, ValueError):
        return ""


@app.get("/where")
async def where(request: Request):
    """Where the working server is. Asked by the app when it starts and when it loses it."""
    if not _key_ok(request):
        raise HTTPException(401, "This is a private Wingman server.")
    return {"url": _where()}


@app.post("/where")
async def moved(request: Request):
    """The working server saying where it now is."""
    if not _key_ok(request):
        raise HTTPException(401, "This is a private Wingman server.")
    url = str((await request.json()).get("url") or "").rstrip("/")
    if not url.startswith("https://"):
        raise HTTPException(400, "An https address is needed.")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"url": url}))
    return {"url": url}


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
async def pass_on(path: str, request: Request):
    target = _where()
    if not target:
        raise HTTPException(503, "The Wingman server has not said where it is yet.")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP}
    try:
        answer = await _http.request(request.method, f"{target}/{path}", params=request.query_params,
                                     content=await request.body(), headers=headers)
    except httpx.HTTPError as error:
        raise HTTPException(502, f"The Wingman server could not be reached: {type(error).__name__}") from error
    passed = {k: v for k, v in answer.headers.items()
              if k.lower() not in {"content-length", "content-encoding", "transfer-encoding", "connection"}}
    return Response(content=answer.content, status_code=answer.status_code, headers=passed)
