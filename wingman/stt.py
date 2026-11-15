"""Smallest Pulse streaming speech-to-text.

Audio goes up as raw mono PCM16; finished stretches of speech come back as Segments with
word timings. Pulse can label speakers too, but that is switched off on this account, so
by default a Segment has no speaker and speakers.py works out who said what from the audio.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode

import websockets

from wingman import config


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    speaker: int | None
    speaker_confidence: float


@dataclass(frozen=True)
class Segment:
    """Words one speaker said in a row, with times in seconds from the start of the stream."""

    text: str
    start: float
    end: float
    speaker: int | None
    speaker_confidence: float
    words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class Interim:
    """Words heard so far in a stretch that has not finished; no speaker is known yet."""

    text: str
    start: float
    end: float


def split_by_speaker(words: list[Word]) -> list[Segment]:
    segments, run = [], []
    for word in words:
        if run and word.speaker != run[-1].speaker:
            segments.append(_segment(run))
            run = []
        run.append(word)
    if run:
        segments.append(_segment(run))
    return segments


def _segment(run: list[Word]) -> Segment:
    confidence = sum(w.speaker_confidence for w in run) / len(run)
    return Segment(
        text=" ".join(w.text for w in run),
        start=run[0].start,
        end=run[-1].end,
        speaker=run[0].speaker,
        speaker_confidence=confidence,
        words=tuple(run),
    )


class PulseStream:
    """One live connection. Feed audio with send(); read Segments and Interims from events()."""

    def __init__(self, eou_timeout_ms: int = 350, diarize: bool = False):
        params = {
            "model": config.STT_MODEL,
            "language": os.environ.get("STT_LANGUAGE") or "en",  # "multi" also hears Hindi, at some cost to English
            "encoding": "linear16",
            "sample_rate": str(config.SAMPLE_RATE),
            "word_timestamps": "true",
            "eou_timeout_ms": str(eou_timeout_ms),
            "keywords": "Wingman:3",  # so its own name is heard
        }
        if diarize:  # needs the account to have Pulse diarization switched on
            params["diarize"] = "true"
        self.url = f"wss://{config.SMALLEST_HOST}/waves/v1/stt/live?{urlencode(params)}"
        self.ws = None
        self.closed = False

    async def __aenter__(self):
        headers = {"Authorization": f"Bearer {config.require('SMALLEST_API_KEY')}"}
        self.ws = await websockets.connect(self.url, additional_headers=headers, max_size=None)
        return self

    async def __aexit__(self, *exc):
        if self.ws is not None:
            await self.ws.close()

    async def send(self, pcm: bytes):
        await self.ws.send(pcm)

    async def finalize(self):
        """Ask for the words heard so far now, without waiting for a pause."""
        await self.ws.send(json.dumps({"type": "finalize"}))

    async def finish(self):
        """No more audio: Pulse sends what is left and then ends events()."""
        if not self.closed:
            self.closed = True
            await self.ws.send(json.dumps({"type": "close_stream"}))

    async def events(self) -> AsyncIterator[Segment | Interim]:
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "error":
                    raise RuntimeError(
                        f"Pulse: {message.get('error_code')}: {message.get('message')}"
                    )
                if kind != "transcription":
                    continue
                text = (message.get("transcript") or "").strip()
                if not message.get("is_final"):
                    if text:
                        start = float(message.get("start") or 0)
                        yield Interim(text, start, start + float(message.get("duration") or 0))
                elif text:
                    words = [
                        Word(
                            text=w.get("word", ""),
                            start=float(w.get("start") or 0),
                            end=float(w.get("end") or 0),
                            speaker=w.get("speaker"),
                            speaker_confidence=float(w.get("speaker_confidence") or 0),
                        )
                        for w in message.get("words") or []
                    ]
                    if words:
                        for segment in split_by_speaker(words):
                            yield segment
                    else:
                        start = float(message.get("start") or 0)
                        yield Segment(text, start, start + float(message.get("duration") or 0),
                                      None, 0.0)
                if message.get("is_last"):
                    return
        except websockets.ConnectionClosedOK:
            return


async def transcribe_pcm(pcm: bytes, realtime: bool = True) -> list[Segment]:
    """Send a whole recording through the live connection, as a microphone would."""
    chunk = config.SAMPLE_RATE * 2 // 10  # 100 ms of PCM16
    segments: list[Segment] = []
    async with PulseStream() as stream:

        async def feed():
            for offset in range(0, len(pcm), chunk):
                await stream.send(pcm[offset : offset + chunk])
                await asyncio.sleep(0.1 if realtime else 0.01)
            await stream.finish()

        feeder = asyncio.create_task(feed())
        async for event in stream.events():
            if isinstance(event, Segment):
                segments.append(event)
        await feeder
    return segments
