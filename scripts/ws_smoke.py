"""Drive the running server the way the phone does: enrol a voice, then replay a conversation.

    uv run python -m scripts.ws_smoke [ws://127.0.0.1:8787/ws]
"""

import asyncio
import json
import sys
import time

import websockets

from scripts.scenarios import ENROL, OWNER, SCENARIOS, silence, speech
from wingman import config

CHUNK = config.SAMPLE_RATE * 2 // 10


async def send_audio(ws, pcm: bytes):
    began = time.monotonic()
    for index, offset in enumerate(range(0, len(pcm), CHUNK)):
        await ws.send(pcm[offset: offset + CHUNK])
        await asyncio.sleep(max(0, began + (index + 1) * 0.1 - time.monotonic()))


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8787/ws"
    scenario = next(s for s in SCENARIOS if s.name == "name-stall")
    pcm = silence(0.5)
    for say in scenario.script:
        pcm += await speech(say.text, say.voice) + silence(say.gap)
    async with websockets.connect(url, max_size=None) as ws:
        async def show():
            async for raw in ws:
                event = json.loads(raw)
                if event["type"] in ("interim", "speech"):
                    continue
                if event["type"] == "audio":
                    event["pcm"] = f"<{len(event['pcm'])} base64 chars>"
                print(event)

        printer = asyncio.create_task(show())
        await ws.send(json.dumps({"type": "enroll_start", "name": "Test owner"}))
        await send_audio(ws, await speech(ENROL, OWNER))
        await ws.send(json.dumps({"type": "enroll_stop"}))
        await asyncio.sleep(1)
        await ws.send(json.dumps({"type": "start"}))
        await asyncio.sleep(1.5)
        await send_audio(ws, pcm)
        await ws.send(json.dumps({"type": "stop"}))
        await asyncio.sleep(6)
        printer.cancel()


if __name__ == "__main__":
    asyncio.run(main())
