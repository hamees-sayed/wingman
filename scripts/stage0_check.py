"""Stage 0: do the providers work, and does Pulse label speakers while streaming?

Builds a short two-voice recording with Lightning, sends it through the live Pulse connection
at real-time speed, and reports whether each line came back with the right speaker and how
long after the words were spoken the text arrived.

    uv run python -m scripts.stage0_check
"""

import asyncio
import time
import wave

import httpx

from wingman import config, stt, tts

OWNER, FRIEND = "blake", "kaitlyn"
LINES = [
    (OWNER, "Hey, good to see you. How was the trip to Lisbon?"),
    (FRIEND, "It was great. We stayed near the river and walked everywhere."),
    (OWNER, "Nice. I'll send you the budget sheet by Friday, by the way."),
    (FRIEND, "Perfect, thanks. My colleague Rahul will need it too."),
    (OWNER, "Sure. What was the name of that restaurant you mentioned?"),
    (FRIEND, "It was called Ponto Final, right on the water."),
]
GAP_SECONDS = 0.7


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(config.SAMPLE_RATE * seconds)


async def build() -> tuple[bytes, list[tuple[str, str, float, float]]]:
    pcm, spans = silence(0.5), []
    for voice, text in LINES:
        audio = await tts.synthesize(text, voice)
        start = len(pcm) / 2 / config.SAMPLE_RATE
        pcm += audio
        spans.append((voice, text, start, len(pcm) / 2 / config.SAMPLE_RATE))
        pcm += silence(GAP_SECONDS)
    return pcm, spans


async def check_openai() -> float:
    began = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{config.OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {config.require('OPENAI_API_KEY')}"},
            json={
                "model": config.GATE_MODEL,
                "messages": [{"role": "user", "content": 'Reply with JSON only: {"ok": true}'}],
                "reasoning_effort": "none",
                "max_completion_tokens": 50,
            },
        )
    if response.status_code != 200:
        raise SystemExit(f"OpenAI {response.status_code}: {response.text[:400]}")
    print("OpenAI reply:", response.json()["choices"][0]["message"]["content"])
    return time.monotonic() - began


async def main():
    print(f"OpenAI {config.GATE_MODEL}: {await check_openai():.2f} s round trip")

    began = time.monotonic()
    pcm, spans = await build()
    seconds = len(pcm) / 2 / config.SAMPLE_RATE
    print(f"Lightning: {len(LINES)} lines, {seconds:.1f} s of audio, "
          f"{time.monotonic() - began:.1f} s to synthesise")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(config.DATA_DIR / "stage0.wav"), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(config.SAMPLE_RATE)
        out.writeframes(pcm)

    chunk = config.SAMPLE_RATE * 2 // 10
    arrivals: list[tuple[stt.Segment, float]] = []
    async with stt.PulseStream() as stream:
        began = time.monotonic()

        async def feed():
            for index, offset in enumerate(range(0, len(pcm), chunk)):
                await stream.send(pcm[offset : offset + chunk])
                # Hold to real time, as a microphone would deliver it.
                await asyncio.sleep(max(0, began + (index + 1) * 0.1 - time.monotonic()))
            await stream.finish()

        feeder = asyncio.create_task(feed())
        async for event in stream.events():
            if isinstance(event, stt.Segment):
                arrivals.append((event, time.monotonic() - began))
        await feeder

    print("\nWhat Pulse returned (speaker, confidence, spoken at, text arrived after end):")
    for segment, arrived in arrivals:
        print(f"  S{segment.speaker} {segment.speaker_confidence:.2f}  "
              f"{segment.start:5.1f}-{segment.end:5.1f}s  +{arrived - segment.end:4.2f}s  "
              f"{segment.text}")

    # Score: which Pulse speaker covers most of each scripted line?
    label_of, right, delays = {}, 0, []
    for voice, text, start, end in spans:
        votes: dict[int | None, float] = {}
        for segment, arrived in arrivals:
            for word in segment.words:
                if start - 0.2 <= (word.start + word.end) / 2 <= end + 0.2:
                    votes[word.speaker] = votes.get(word.speaker, 0) + (word.end - word.start)
        last = [a for s, a in arrivals if start - 0.2 <= s.start <= end + 0.2]
        if last:
            delays.append(max(last) - end)
        if not votes:
            print(f"  MISSING: {text}")
            continue
        winner = max(votes, key=votes.get)
        share = votes[winner] / sum(votes.values())
        expected = label_of.setdefault(voice, winner)
        ok = winner == expected and len(set(label_of.values())) == len(label_of)
        right += ok
        print(f"  {'ok ' if ok else 'BAD'} {voice:8s} -> S{winner} ({share:.0%} of words)  {text}")
    delays.sort()
    print(f"\nSpeaker right on {right}/{len(spans)} lines; voices mapped to {label_of}")
    if delays:
        print(f"Text arrived after a line ended: median {delays[len(delays) // 2]:.2f} s, "
              f"slowest {delays[-1]:.2f} s")


if __name__ == "__main__":
    asyncio.run(main())
