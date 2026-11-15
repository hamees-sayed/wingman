"""Wingman's memory lives in Convex; this is the server's way in.

Calls go over Convex's HTTP API so they can be awaited. Function names are "file:function",
matching the files under convex/.
"""

import os

import httpx
from dotenv import dotenv_values

from wingman import config, users


def convex_url() -> str:
    url = os.environ.get("CONVEX_URL") or dotenv_values(config.ROOT / ".env.local").get("CONVEX_URL")
    if not url:
        raise SystemExit("CONVEX_URL is not set; run `npx convex dev` in the project folder first")
    return url.rstrip("/")


class StoreError(RuntimeError):
    pass


class Store:
    def __init__(self, url: str | None = None):
        self.url = url or convex_url()
        self.http = httpx.AsyncClient(base_url=self.url, timeout=15)

    async def _call(self, kind: str, path: str, args: dict):
        clean = {key: value for key, value in args.items() if value is not None}
        who = users.user()
        if who != users.OWNER:  # the first owner's rows carry no account, as before accounts existed
            clean["userId"] = who
        try:
            response = await self.http.post(
                f"/api/{kind}", json={"path": path, "args": clean, "format": "json"}
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise StoreError(f"Convex {path}: {type(error).__name__}: {error}") from error
        if data.get("status") != "success":
            raise StoreError(f"Convex {path}: {data.get('errorMessage', response.text[:200])}")
        return data.get("value")

    async def query(self, path: str, **args):
        return await self._call("query", path, args)

    async def mutation(self, path: str, **args):
        return await self._call("mutation", path, args)

    async def close(self):
        await self.http.aclose()
