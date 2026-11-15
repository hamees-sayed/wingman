"""One small helper: ask an OpenAI-compatible chat model for a JSON object."""

import json
import re

import httpx

from wingman import config

_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.OPENAI_BASE_URL,
            headers={"Authorization": f"Bearer {config.require('OPENAI_API_KEY')}"},
            timeout=httpx.Timeout(12.0, connect=4.0),
        )
    return _client


async def ask_json(system: str, user: str, model: str | None = None, max_tokens: int = 400,
                   timeout: float | None = None) -> dict:
    """Returns the model's JSON object, or {} when the call or the parse fails.

    A failure must never make Wingman speak, so callers treat {} as "nothing to say".
    """
    body = {
        "model": model or config.GATE_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",
        "max_completion_tokens": max_tokens,
    }
    try:
        response = await _http().post("/chat/completions", json=body, timeout=timeout or httpx.USE_CLIENT_DEFAULT)
        if response.status_code == 400 and "reasoning_effort" in response.text:
            body.pop("reasoning_effort")  # older models do not take it
            response = await _http().post("/chat/completions", json=body)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0)) if match else {}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return {}
