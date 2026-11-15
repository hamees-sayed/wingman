"""Smallest Lightning text-to-speech: text in, mono PCM16 at SAMPLE_RATE out."""

import asyncio

import httpx

from wingman import config

# Smallest allows one synthesis in flight per account, so calls are serialised here.
_lock = asyncio.Lock()


async def synthesize(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
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
    async with _lock, httpx.AsyncClient(timeout=60) as client:
        for attempt in range(4):
            response = await client.post(url, json=body, headers=headers)
            if response.status_code != 429:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
        response.raise_for_status()
        return response.content
