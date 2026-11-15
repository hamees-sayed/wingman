"""Scripted two-voice conversations run through the real pipeline.

Each scenario is spoken by Lightning voices, replayed at real time into a Session with the
real Pulse, voice model, OpenAI and Convex, and checked on what Wingman said and saved.

    uv run python -m scripts.scenarios            # all
    uv run python -m scripts.scenarios name ask   # those whose name starts with these

This empties the Convex tables before each scenario, so point it at a development database.
"""

import asyncio
import hashlib
import re
import sys
import time
from dataclasses import dataclass, field

from wingman import config, speakers, tts
from wingman.session import Session
from wingman.store import Store

OWNER, FRIEND, THIRD = "blake", "kaitlyn", "sam"
RATE = config.SAMPLE_RATE
CACHE = config.DATA_DIR / "tts-cache"

ENROL = ("This is my normal speaking voice. I am reading a couple of sentences so that Wingman "
         "can learn how I sound and tell me apart from other people.")


@dataclass
class Say:
    voice: str
    text: str
    gap: float = 0.7  # silence after the line


@dataclass
class Scenario:
    name: str
    script: list[Say]
    spoken: list[tuple[str, str]] = field(default_factory=list)  # (kind, words it must contain)
    silent: bool = False  # nothing may be spoken
    promises: list[tuple[str, str]] = field(default_factory=list)  # (by, words in "what")
    people: list[str] = field(default_factory=list)  # names that must be saved
    labels: list[str] = field(default_factory=list)  # labels that must appear on lines
    seed: str = ""  # name of a seeding step run before the conversation
    max_latency: float = 3.0


SMALL_TALK = [
    Say(OWNER, "Hey, good to see you. How was the trip to Lisbon?"),
    Say(FRIEND, "It was great. We stayed near the river and walked everywhere."),
    Say(OWNER, "That sounds lovely. Did you get to try the custard tarts?"),
    Say(FRIEND, "Every single morning. I think I ate about twenty of them."),
]

SCENARIOS = [
    Scenario("small-talk", SMALL_TALK + [
        Say(OWNER, "I am so jealous. We should plan something for the spring."),
        Say(FRIEND, "Definitely. Maybe somewhere warm with a beach.", gap=3.0),
    ], silent=True),
    Scenario("name-stall", [
        Say(FRIEND, "My colleague Rahul from the design team just bought a bright red bike."),
        Say(OWNER, "Nice. I have been meaning to start cycling to work again."),
        Say(FRIEND, "You should. The new bike lanes make it so much easier."),
        Say(OWNER, "I actually met him at the offsite last month. What's his name, the guy "
                   "from design...", gap=5.0),
    ], spoken=[("name", "rahul|raul")]),
    Scenario("other-stalls", [
        Say(OWNER, "The offsite last month was really well organised."),
        Say(FRIEND, "It was. I spoke to someone from your finance team for ages. What's her "
                    "name, the one with the red glasses...", gap=5.0),
    ], silent=True),
    Scenario("name-never-said", [
        Say(FRIEND, "We finally hired someone to run finance."),
        Say(OWNER, "Oh good. I think I saw the announcement. What's her name again...", gap=5.0),
    ], silent=True),
    Scenario("number-stall", [
        Say(OWNER, "We signed for the flat. The deposit is thirteen thousand four hundred."),
        Say(FRIEND, "That is a lot of money. When do you move in?"),
        Say(OWNER, "The first of March, if the paperwork goes through."),
        Say(FRIEND, "Exciting. And remind me, how much did you have to put down?"),
        Say(OWNER, "It was, um, I forget the number...", gap=5.0),
    ], spoken=[("fact", "thirteen thousand")]),
    Scenario("promise-capture", SMALL_TALK[:2] + [
        Say(OWNER, "By the way, I'll send you the budget sheet by Friday."),
        Say(FRIEND, "Perfect, thanks. And I'll introduce you to Sam next week.", gap=4.0),
    ], silent=True, promises=[("you", "budget"), ("them", "sam")]),
    Scenario("introduction", [
        Say(OWNER, "Hi there, I don't think we have met."),
        Say(FRIEND, "Hi, I'm Priya. I lead the design team at Acme."),
        Say(OWNER, "Great to meet you. I have heard good things about your team."),
        Say(FRIEND, "That is kind of you to say. We have been busy this year.", gap=5.0),
    ], silent=True, people=["Priya"], labels=["Priya"]),
    Scenario("promise-returns", [
        Say(OWNER, "Morning. Did you have a good weekend?"),
        Say(FRIEND, "I did, thanks. We went hiking on Saturday and it was beautiful.", gap=4.0),
        Say(OWNER, "That sounds great. I stayed in and read.", gap=2.0),
    ], seed="priya-owed-deck", spoken=[("promise", "deck")], labels=["Priya"]),
    Scenario("ask", [
        Say(FRIEND, "We had dinner at a place called Ponto Final, right on the water."),
        Say(OWNER, "I have heard of it. Was it hard to get a table?"),
        Say(FRIEND, "We queued for about forty minutes, but it was worth it."),
        Say(OWNER, "Wingman, what was the restaurant called?", gap=6.0),
    ], spoken=[("any", "ponto")], max_latency=4.0),
]


async def speech(text: str, voice: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(f"{config.TTS_MODEL}|{voice}|{text}".encode()).hexdigest() + ".pcm")
    if not path.exists():
        path.write_bytes(await tts.synthesize(text, voice))
    return path.read_bytes()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(RATE * seconds)


async def seed(name: str, store: Store, embedder: speakers.Embedder):
    if name == "priya-owed-deck":
        clip = await speech("Hi, I'm Priya. I lead the design team at Acme, and I have been "
                            "here for about three years now.", FRIEND)
        priya = await store.mutation(
            "people:upsert", name="Priya", about="leads design at Acme",
            voiceprint=embedder.embed(clip).tolist(), voiceSeconds=len(clip) / 2 / RATE,
        )
        earlier = await store.mutation("conversations:start")
        await store.mutation("conversations:addPerson", id=earlier, personId=priya)
        await store.mutation("conversations:end", id=earlier, title="Deck review",
                             summary="You agreed to send Priya the deck.")
        await store.mutation("promises:add", conversationId=earlier, by="you", personId=priya,
                             person="Priya", what="the deck", due="by Friday")


async def run(scenario: Scenario, store: Store, embedder: speakers.Embedder) -> bool:
    await store.mutation("settings:wipe")
    enrol = await speech(ENROL, OWNER)
    await store.mutation("people:upsert", name="Owner", isOwner=True,
                         voiceprint=embedder.embed(enrol).tolist(),
                         voiceSeconds=len(enrol) / 2 / RATE)
    if scenario.seed:
        await seed(scenario.seed, store, embedder)

    pcm = silence(0.5)
    for say in scenario.script:
        pcm += await speech(say.text, say.voice) + silence(say.gap)

    events: list[dict] = []

    async def emit(event: dict):
        events.append({**event, "_t": session.now})

    session = Session(store, emit, embedder, demo=True)
    await session.start()
    chunk, began = RATE * 2 // 10, time.monotonic()
    for index, offset in enumerate(range(0, len(pcm), chunk)):
        await session.feed(pcm[offset: offset + chunk])
        await asyncio.sleep(max(0, began + (index + 1) * 0.1 - time.monotonic()))
    await session.end()

    lines = [e for e in events if e["type"] == "line"]
    whispers = [e for e in events if e["type"] == "whisper"]
    spoken = [w for w in whispers if w["outcome"] == "spoken"]
    recap = await store.query("conversations:recap", id=session.conversation)
    people = await store.query("people:list")
    final_lines = await store.query("conversations:lines", conversationId=session.conversation)

    problems = []
    if scenario.silent and spoken:
        problems.append(f"spoke when it should not: {[w['text'] for w in spoken]}")
    for kind, words in scenario.spoken:
        hit = next((w for w in spoken if (kind == "any" or w["kind"] == kind)
                    and any(option in w["text"].lower() for option in words.split("|"))), None)
        if hit is None:
            problems.append(f"no spoken {kind} containing '{words}'")
        elif hit["latency"] is not None and hit["latency"] > scenario.max_latency:
            problems.append(f"{kind} took {hit['latency']:.1f} s (limit {scenario.max_latency})")
    if not scenario.silent and len(spoken) > len(scenario.spoken):
        problems.append(f"extra whispers: {[w['text'] for w in spoken]}")
    for by, words in scenario.promises:
        if not any(p["by"] == by and words in (p["what"] + " " + p["person"]).lower()
                   for p in recap["promises"]):
            problems.append(f"no promise by {by} about '{words}'")
    if scenario.silent and not scenario.promises and recap["promises"]:
        problems.append(f"unexpected promises: {[p['what'] for p in recap['promises']]}")
    for name in scenario.people:
        if not any(p["name"].lower() == name.lower() for p in people):
            problems.append(f"{name} was not saved as a person")
    for label in scenario.labels:
        if not any(line["label"] == label for line in final_lines):
            problems.append(f"no line labelled {label}")
    # Each line is matched to the scripted sentence it came from: the owner's must be
    # labelled You and nobody else's may be. Lines too short to judge may stay Unknown.
    def bag(text):
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    wrong = unknown = 0
    for line in final_lines:
        words = bag(line["text"])
        say = max(scenario.script, key=lambda s: len(words & bag(s.text)) / (len(words) or 1))
        mine = say.voice == OWNER
        if line["who"] == "unknown":
            unknown += len(words) >= 4
        elif (line["who"] == "you") != mine:
            wrong += 1
            problems.append(f"wrong speaker: [{line['label']}] {line['text']}")
    if unknown:
        problems.append(f"{unknown} full lines left Unknown")

    print(f"\n=== {scenario.name}: {'PASS' if not problems else 'FAIL'}")
    for line in final_lines:
        print(f"   [{line['label']:>9}] {line['text']}")
    for w in whispers:
        latency = f" {w['latency']:.1f}s" if w.get("latency") is not None else ""
        print(f"   ~ {w['outcome']:8} {w['kind']:7} conf {w['confidence']:.2f}{latency} "
              f"\"{w['text']}\"  ({w['why']})")
    for p in recap["promises"]:
        print(f"   * promise by {p['by']}: {p['person']} / {p['what']} / {p.get('due', '')}")
    for e in events:
        if e["type"] == "error":
            print("   ! error:", e["message"])
            problems.append("error event")
    for problem in problems:
        print("   FAIL:", problem)
    return not problems


async def main():
    wanted = sys.argv[1:]
    chosen = [s for s in SCENARIOS if not wanted or any(s.name.startswith(w) for w in wanted)]
    store, embedder = Store(), speakers.Embedder()
    results = {}
    for scenario in chosen:
        results[scenario.name] = await run(scenario, store, embedder)
    await store.close()
    passed = sum(results.values())
    print(f"\n{passed}/{len(results)} passed: "
          + ", ".join(f"{name} {'ok' if ok else 'FAIL'}" for name, ok in results.items()))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
