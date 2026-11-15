"""Smallest Lightning text-to-speech: text in, mono PCM16 at SAMPLE_RATE out."""

import asyncio

import httpx

from wingman import config

# Smallest allows one synthesis in flight per account, so calls are serialised here.
_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60)
    return _client


# Short stock lines ("Let me check.") are kept once made, so they can be said without a wait.
_kept: dict[tuple[str, str | None, float], bytes] = {}
FILLERS = ("Checking your calendar.", "Checking your to-do list.", "Checking your promises.",
           "Checking your recent Slack messages.", "Checking your recent conversations.",
           "Going through Slack for your tasks.", "Pulling up the research.")


async def warm():
    """Make the stock lines ahead of time."""
    for line in FILLERS:
        try:
            await synthesize(line)
        except Exception:  # noqa: BLE001 - a missing filler only costs a moment later
            pass


async def synthesize(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
    key = (text, voice, speed)
    if key in _kept:
        return _kept[key]
    pcm = await _make(text, voice, speed)
    if len(text) <= 40 and len(_kept) < 80:
        _kept[key] = pcm
    return pcm


async def _make(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
    body = {
        "text": text,
        "voice_id": voice or config.TTS_VOICE,
        "model": config.TTS_MODEL,
        "sample_rate": config.SAMPLE_RATE,
        "output_format": "pcm",
        "language": "en",
        "speed": speed,
    }
    headers = {"Authorization": f"Bearer {config.require('SMALLEST_API_KEY')}"}
    url = f"https://{config.SMALLEST_HOST}/waves/v1/tts"
    async with _lock:
        client = _http()  # one connection kept open: setting up a new one costs more than the speech
        for attempt in range(4):
            response = await client.post(url, json=body, headers=headers)
            if response.status_code != 429:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
        response.raise_for_status()
        return response.content
