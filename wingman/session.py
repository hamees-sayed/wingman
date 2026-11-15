"""One conversation: audio in; lines, notes and the occasional whisper out.

The same Session runs from a recording, the web console's microphone or the phone. All timing
is in conversation seconds, counted from the audio fed in, so a recording replayed at real
time behaves exactly like a live microphone.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable

import numpy as np
import sherpa_onnx

from wingman import actions, agent, brain, config, google, notion, slack, speakers, stt, tts
from wingman import profile
from wingman.brain import Candidate, Line
from wingman.store import Store, StoreError
from wingman.whisperer import PAUSE_NEEDED, Governor

RATE = config.SAMPLE_RATE
VAD_MODEL = config.ROOT / "models" / "silero_vad.onnx"
KEEP_AUDIO_SECONDS = 180  # audio is held only this long, in memory, to tell speakers apart
TRAIL_SILENCE = 1.0  # you trailed off and stayed quiet this long
ASKED_SILENCE = 1.2  # someone asked you something and you stayed quiet this long
TRIGGER_GAP = 2.5  # at least this long between unprompted model calls
ASSIST_GAP = 8.0  # at least this long between looks for something worth stepping in with
ASSIST_GAP_DEMO = 3.0
REJOIN_WITHIN = 300.0  # the same people speaking again this soon are still in one conversation
REJOIN_WITHIN_DEMO = 90.0
# Said at the end of a conversation; after one of these a short silence is enough to close it.
GOODBYE = re.compile(
    r"\b(bye|goodbye|see you|see ya|talk (to you )?(later|soon|tomorrow)|catch you later|take care|"
    r"have a (good|great|nice) (one|day|night|evening|weekend)|good night|gotta go|got to go|"
    r"speak (soon|later)|thanks,? (bye|everyone|all)|that's (all|it) (for|from) (today|now|me))\b", re.I)
CUT_AFTER = 0.25  # speech lasting this long during a whisper stops it

Emit = Callable[[dict], Awaitable[None]]

# Sessions listening right now, so the server can speak to the owner wherever they are.
ACTIVE: list["Session"] = []


class Vad:
    """Is anyone speaking right now."""

    def __init__(self):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(VAD_MODEL)
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = 0.2
        cfg.silero_vad.min_speech_duration = 0.1
        cfg.sample_rate = RATE
        self.window = cfg.silero_vad.window_size
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
        self.rest = np.zeros(0, dtype=np.float32)

    def feed(self, pcm: bytes) -> bool:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        self.rest = np.concatenate([self.rest, samples])
        while len(self.rest) >= self.window:
            self.vad.accept_waveform(self.rest[: self.window])
            self.rest = self.rest[self.window :]
        while not self.vad.empty():
            self.vad.pop()
        return self.vad.is_speech_detected()


class Session:
    def __init__(self, store: Store, emit: Emit, embedder: speakers.Embedder,
                 eagerness: str = "normal", demo: bool = False):
        self.store, self.emit, self.embedder = store, emit, embedder
        self.governor = Governor(eagerness=eagerness, demo=demo)
        self.vad = Vad()
        self.roster = speakers.Roster()
        self.conversation: str | None = None
        self.lines: list[Line] = []
        self.people: list[dict] = []
        self.old_promises: list[dict] = []  # open before this conversation began
        self.audio = bytearray()
        self.audio_offset = 0  # bytes already dropped from the front of self.audio
        self.fed = 0  # bytes fed in total
        self.speaking = False
        self.speech_began = 0.0
        self.last_speech = 0.0
        self.pending: Candidate | None = None
        self.delivering = False
        self.playing: tuple[str | None, Candidate, float, float] | None = None  # id, what, from, until
        self.trail: Line | None = None
        self.asked: Line | None = None
        self.resolving = False
        self.last_trigger = -100.0
        self.triggered_utterances: set[float] = set()
        self.unextracted: list[Line] = []
        self.extracting: asyncio.Task | None = None
        self.tasks: set[asyncio.Task] = set()
        self.stream: stt.PulseStream | None = None
        self.reader: asyncio.Task | None = None
        self.ended = False
        self.engaged_until = -1.0  # after Wingman answers, a follow-up needs no "Wingman"
        self.asked_to_add = -1.0  # until when a plain "yes" or "no" answers "should I add them?"
        self.assisting = False
        self.clips: dict[str, asyncio.Task] = {}  # whisper audio being prepared ahead of the pause
        self.waiting: Candidate | None = None  # the whisper waiting for a gap to be said in
        self.answered: set[str] = set()  # cues the owner no longer needs: they have already replied
        self.checkin: tuple[str, float] | None = None  # a question Wingman asked, and until when an answer counts
        self.last_assist = -100.0
        self.assisted_upto = 0  # lines already considered for a nudge or an explanation
        self.cues: list[str] = []  # nudges and explanations already offered
        self.offset = 0.0  # added to line times when this session continues an earlier conversation
        self.goodbye_at = -1.0  # when someone last said goodbye
        self.previous: dict | None = None  # the conversation that just closed, in case it carries on
        self.spoke: list[tuple[float, float]] = []  # when Wingman's own voice was playing
        self.peak = 0  # loudest sample so far, to notice a dead microphone
        self.warned_silent = False

    # --- Lifecycle -----------------------------------------------------------------------

    @property
    def now(self) -> float:
        return self.fed / 2 / RATE

    async def start(self, continued: bool = False):
        ACTIVE.append(self)
        voices, self.people, promises, grades = await asyncio.gather(
            self.store.query("people:voices"),
            self.store.query("people:list"),
            self.store.query("promises:open"),
            self.store.query("whispers:grades"),
        )
        self.roster = speakers.Roster.from_people(voices)
        self.old_promises = promises
        self.governor.learn(grades)
        self.conversation = await self.store.mutation("conversations:start")
        self.stream = await stt.PulseStream().__aenter__()
        self.reader = asyncio.create_task(self._read())
        await self.emit({
            "type": "started", "conversation": self.conversation,
            "ownerEnrolled": self.roster.has_owner, "demo": self.governor.demo,
            "continued": continued,  # always-on rolled into a new conversation: keep the screen
        })

    def continue_from(self, earlier: "Session"):
        """Always-on rolled over from `earlier`. Keep its voices, so "Speaker 2" stays the same
        person, and remember it in case the same people speak again soon."""
        for key, speaker in earlier.roster.speakers.items():
            if key not in self.roster.speakers:
                speaker.session_seconds = 0.0
                self.roster.speakers[key] = speaker
        self.roster.next_anon = max(self.roster.next_anon, earlier.roster.next_anon)
        self.previous = {
            "conversation": earlier.conversation, "closed": time.time(),
            "length": earlier.now + earlier.offset,
            "voices": {line.label for line in earlier.lines if line.who != "unknown"},
            "lines": list(earlier.lines),
        }

    @property
    def said_goodbye(self) -> bool:
        """Someone said goodbye and nothing has been said since."""
        return self.goodbye_at >= 0 and (not self.lines or self.lines[-1].start <= self.goodbye_at + 0.01)

    async def _maybe_rejoin(self, runs) -> None:
        """First words after a rollover. If it is the same people within a few minutes, this is
        the earlier conversation continuing, not a new one; a new voice means a new conversation."""
        previous, self.previous = self.previous, None
        if previous is None or self.lines:
            return
        window = REJOIN_WITHIN_DEMO if self.governor.demo else REJOIN_WITHIN
        gap = time.time() - previous["closed"]
        voices = {run.speaker.label for run in runs if run.speaker.who != "unknown"}
        if gap > window or not voices or not voices <= (previous["voices"] | {"You"}):
            return
        fresh = self.conversation
        try:
            await self.store.mutation("conversations:reopen", id=previous["conversation"])
            await self.store.mutation("conversations:remove", id=fresh)
        except StoreError:
            return
        self.conversation = previous["conversation"]
        self.offset = previous["length"] + gap - self.now
        self.lines = previous["lines"]
        await self.emit({"type": "resumed", "conversation": self.conversation})

    @property
    def idle(self) -> float:
        """Seconds since anyone spoke."""
        return self.now - self.last_speech

    @property
    def busy(self) -> bool:
        return bool(self.pending or self.delivering or self.playing or self.resolving)

    async def end(self, rolling: bool = False) -> dict | None:
        """Close the conversation and write its recap. With rolling, listening carries on in
        a new conversation, so the screen is told "recap", not "ended"."""
        done = "recap" if rolling else "ended"
        if self.ended:
            return None
        self.ended = True
        if self in ACTIVE:
            ACTIVE.remove(self)
        if self.stream is not None:
            try:
                await self.stream.finish()
                await asyncio.wait_for(self.reader, timeout=8)
            except (TimeoutError, Exception):  # noqa: BLE001 - ending must not fail
                self.reader.cancel()
            await self.stream.__aexit__(None, None, None)
        if self.extracting is not None:
            await asyncio.gather(self.extracting, return_exceptions=True)
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if not self.lines:
            try:
                await self.store.mutation("conversations:remove", id=self.conversation)
            except StoreError:
                pass  # already gone, for instance after "Delete everything"
            await self.emit({"type": done, "conversation": None})
            return None
        # Named people are remembered by voice for next time.
        for speaker in self.roster.speakers.values():
            if speaker.key != "owner" and speaker.person_id and speaker.session_seconds >= 3:
                await self.store.mutation(
                    "people:upsert", name=speaker.label,
                    voiceprint=speaker.voiceprint.tolist(),
                    voiceSeconds=min(speaker.seconds, 120.0),
                )
        known = []
        try:
            page = await self.store.query("conversations:recap", id=self.conversation)
            known = [p["what"] for p in page["promises"]] + [t["text"] for t in await self.store.query("tasks:open")]
        except StoreError:
            pass
        summary = await brain.recap(self.lines, known)
        todos = summary.pop("todos", [])
        await self.store.mutation("conversations:end", id=self.conversation, **summary)
        await self.emit({"type": done, "conversation": self.conversation, **summary})
        await self._suggest(todos)
        mine = sum(len(line.text.split()) for line in self.lines if line.who == "you" and not line.retracted)
        if mine >= 12:  # what the owner said about themselves joins what Wingman knows of them
            profile.schedule(self.store, "Conversations", "A conversation the owner (labelled You) just had:\n"
                             + brain.transcript(self.lines, 120))
        return summary

    async def _suggest(self, todos: list[dict]):
        """After a conversation, what the owner should do because of it goes straight onto
        their to-do list. Nothing is said; they see it on Home, marked as added by Wingman."""
        added = 0
        try:
            owed = [_meaning(p["what"] + " " + p["person"]) for p in await self.store.query("promises:open") if p["by"] == "you"]
        except StoreError:
            owed = []
        for todo in todos:
            text = str(todo["text"]).strip().rstrip(".")
            mine = _meaning(text)
            if any(len(mine & other) >= 2 and len(mine & other) >= 0.6 * min(len(mine), len(other)) for other in owed):
                continue  # already on the list as a promise the owner made
            due = actions.parse_when(str(todo.get("when") or ""))
            if not text:
                continue
            try:
                await self.store.mutation("tasks:add", kind="reminder" if due else "note", text=text, due=due,
                                          conversationId=self.conversation, auto=True)
                added += 1
            except StoreError:
                continue
        if added:
            for listener in [self, *ACTIVE]:
                await listener.emit({"type": "task"})

    # --- Audio ---------------------------------------------------------------------------

    async def feed(self, pcm: bytes):
        if self.ended:
            return
        self.audio += pcm
        self.fed += len(pcm)
        extra = len(self.audio) - KEEP_AUDIO_SECONDS * RATE * 2
        if extra > RATE * 2 * 10:
            del self.audio[:extra]
            self.audio_offset += extra
        now = self.now
        self.peak = max(self.peak, int(np.abs(np.frombuffer(pcm, dtype=np.int16)).max(initial=0)))
        # A dead microphone delivers exact zeros; a quiet room still has a little noise.
        if not self.warned_silent and now > 8 and self.peak < 12:
            self.warned_silent = True
            await self.emit({"type": "error", "message":
                             "No sound is reaching Wingman. Check that the microphone is on and "
                             "that this app is allowed to use it."})
        elif self.warned_silent and self.peak >= 12:
            self.warned_silent = False
            await self.emit({"type": "clear_error"})
        speaking = self.vad.feed(pcm)
        if speaking and not self.speaking:
            self.speech_began = now
        if speaking:
            self.last_speech = now
        if speaking != self.speaking:
            self.speaking = speaking
            await self.emit({"type": "speech", "speaking": speaking})
        await self.stream.send(pcm)
        await self._tick()

    def clip(self, start: float, end: float) -> bytes:
        first = max(0, int(start * RATE) * 2 - self.audio_offset)
        last = max(first, int(end * RATE) * 2 - self.audio_offset)
        return bytes(self.audio[first:last])

    # --- Transcription -------------------------------------------------------------------

    async def _read(self):
        try:
            async for event in self.stream.events():
                if isinstance(event, stt.Interim):
                    await self._on_interim(event)
                else:
                    await self._on_final(event)
        except Exception as error:  # noqa: BLE001 - surfaced to the screen, not swallowed
            await self.emit({"type": "error", "message": f"Transcription stopped: {error}"})

    def _owner_is_speaking(self, start: float, least: float = 0.8) -> bool:
        now = self.now
        start = max(start, now - 6.0)
        if now - start < least or not self.roster.has_owner:
            return False
        scored = self.roster.score(self.embedder.embed(self.clip(start, now)))
        return bool(scored) and scored[0][1].key == "owner" and scored[0][0] >= 0.4

    async def _on_interim(self, event: stt.Interim):
        # Half-heard words are not shown: the screen gets each line once, when it is settled.
        utterance = round(event.start, 1)
        kind = brain.stall(event.text)
        if kind and utterance not in self.triggered_utterances and self._owner_is_speaking(event.start):
            self.triggered_utterances.add(utterance)
            self._trigger(
                f'the owner seems to be searching for a {kind} and said: "{event.text[-200:]}"',
                interim=event.text,
            )

    async def _on_final(self, segment: stt.Segment):
        if segment.words:
            runs = speakers.attribute(list(segment.words), self.clip, self.embedder, self.roster)
        else:
            runs = [speakers.Attributed(speakers.UNKNOWN, segment.text, segment.start,
                                        segment.end, 0.0)]
        await self._maybe_rejoin(runs)
        new = []
        for run in runs:
            echoed = sum(max(0.0, min(run.end, b) - max(run.start, a)) for a, b in self.spoke[-6:])
            if run.speaker.who != "you" and echoed > 0.5 * max(0.2, run.end - run.start):
                continue  # that was Wingman itself, heard through a loudspeaker
            line = Line(who=run.speaker.who, label=run.speaker.label, text=run.text,
                        start=run.start + self.offset, end=run.end + self.offset,
                        person_id=run.speaker.person_id)
            try:
                line.id = await self.store.mutation(
                    "conversations:addLine", conversationId=self.conversation, who=line.who,
                    personId=line.person_id, label=line.label, text=line.text,
                    start=line.start, end=line.end,
                )
            except StoreError as error:
                await self.emit({"type": "error", "message": str(error)})
            new.append(line)
            # What people say is kept for memory and recaps, but is not put on the screen.
        utterance = round(segment.start, 1)
        self._on_lines(new, already=utterance in self.triggered_utterances)

    # --- Noticing ------------------------------------------------------------------------

    def _on_lines(self, new: list[Line], already: bool):
        self.lines.extend(new)
        self.trail = self.asked = None
        present = {s.person_id for s in self.roster.speakers.values()
                   if s.person_id and s.session_seconds > 0}
        for line in new:
            if GOODBYE.search(line.text):
                self.goodbye_at = line.start
            pending = self.pending
            if pending and not pending.prompted and _says(line.text, pending.text):
                self.pending = None  # they got there without help
            if line.who == "you" and len(line.text.split()) >= 6:
                # The owner has answered for themselves: a nudge that arrives now is too late.
                for cue in (self.pending, self.waiting):
                    if cue and cue.kind == "nudge" and line.end > cue.born + 1.0:
                        self.answered.add(cue.key)
                        if cue is self.pending:
                            self.pending = None
            if line.who == "you":
                if self.now < self.asked_to_add and len(line.text.split()) <= 8:
                    said = line.text.lower()
                    yes = re.search(r"\b(yes|yeah|yep|sure|go ahead|add (it|them|those)|please do|do it|okay|ok)\b", said)
                    no = re.search(r"\b(no|nope|don't|do not|skip|not now|leave (it|them))\b", said)
                    if yes or no:
                        self.asked_to_add = -1.0
                        line.addressed = True
                        self._answer_suggestions(accept=not no)
                        continue
                request = brain.called(line.text)
                if request is None and self.now < self.engaged_until and len(line.text.split()) >= 2:
                    request = line.text  # carrying on the exchange with Wingman
                if request is not None:
                    if re.fullmatch(r"\W*(stop|thanks|thank you|okay|ok|that's all|never mind)\W*", request, re.I):
                        self.engaged_until = -1.0
                        continue
                    line.addressed = True
                    if not request.strip():
                        # Only the name so far ("Wingman ..."), the request is in the next breath.
                        self.engaged_until = self.now + 8.0
                        continue
                    self._converse(request)
                    continue
                kind = brain.stall(line.text)
                if kind and not already:
                    self._trigger(
                        f'the owner seems to be searching for a {kind} and said: "{line.text}"'
                    )
                elif not kind and brain.trails_off(line.text) and len(line.text.split()) >= 3:
                    self.trail = line
            elif line.who == "other" and line.text.rstrip().endswith("?"):
                self.asked = line
            for promise in self.old_promises:
                candidate = brain.promise_due(promise, line, present, self.now)
                if candidate:
                    self._offer(candidate)
        self._maybe_assist()
        self.unextracted.extend(new)
        if self.extracting is None or self.extracting.done():
            self.extracting = asyncio.create_task(self._extract())

    def check_in(self, question: str):
        """Ask the owner something in a quiet moment; what they say back is remembered."""
        self.checkin = (question, self.now + 90.0)
        # Its own kind, so the phone can keep it to earbuds or a notification, never the speaker.
        self._offer(Candidate("checkin", question, 1.0, "a quiet moment", "Wingman", self.now, prompted=True,
                              key=f"checkin:{self.now:.0f}"))

    def _converse(self, request: str):
        """The owner spoke to Wingman: answer aloud, from everything it knows."""
        if self.checkin and self.now < self.checkin[1]:
            profile.schedule(self.store, "Check-in",
                             f"Wingman asked the owner: {self.checkin[0]}\nThe owner answered: {request}")
        self.checkin = None
        async def reply():
            answer = await agent.chat(self.store, request)
            for task in answer.get("done") or []:
                await self.emit({"type": "task", **{k: v for k, v in task.items() if k != "clash"}})
            self.say(agent.spoken(answer), key=f"reply:{self.now:.1f}")
        task = asyncio.create_task(reply())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _answer_suggestions(self, accept: bool):
        async def settle():
            try:
                count = await self.store.mutation("tasks:answerSuggestions", accept=accept)
            except StoreError:
                return
            await self.emit({"type": "task"})
            if count:
                self.say(("Added." if count == 1 else f"Added all {count}.") if accept else "Okay, I'll leave them.",
                         key=f"answered:{self.now:.1f}")
        task = asyncio.create_task(settle())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def say(self, text: str, key: str = ""):
        """Speak this at the next pause; used for answers, reminders and "research is ready"."""
        if text:
            self._offer(Candidate("ask", text, 1.0, "you asked", "Wingman", self.now, prompted=True,
                                  key=key or f"say:{text[:40]}"))

    def _trigger(self, reason: str, prompted: bool = False, interim: str = ""):
        now = self.now
        if not prompted and (self.resolving or now - self.last_trigger < TRIGGER_GAP):
            return
        self.last_trigger = now
        task = asyncio.create_task(self._resolve(reason, prompted, interim, now))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _resolve(self, reason: str, prompted: bool, interim: str, born: float):
        if not prompted:
            self.resolving = True
        try:
            recent = " ".join(line.text for line in self.lines[-2:]) + " " + interim
            words = [w for w in re.findall(r"[A-Za-z0-9]+", recent) if len(w) >= 4][-12:]
            past = []
            if words:
                try:
                    past = await self.store.query(
                        "conversations:search", text=" ".join(words),
                        exceptConversation=self.conversation, limit=8,
                    )
                except StoreError:
                    past = []
            promises = [p for p in self.old_promises]
            if words:  # facts imported from other assistants count as memory too
                try:
                    known = await self.store.query("memories:search", text=" ".join(words), limit=6)
                    past = past + [{"label": "known about you", "text": m["text"]} for m in known]
                except StoreError:
                    pass
            if words and notion.configured():
                try:
                    found = await asyncio.wait_for(notion.search(" ".join(words[-5:]), pages=2, timeout=2), 2.5)
                    past = past + [{"label": f"Notion page {p['title']}", "text": p["text"][:600]} for p in found]
                except (TimeoutError, asyncio.TimeoutError):
                    pass
            if words and slack.configured():
                try:
                    found = await asyncio.wait_for(slack.search(" ".join(words[-4:]), count=3, timeout=2), 2.5)
                    past = past + [{"label": f"Slack, {m['who']}", "text": m["text"][:300]} for m in found]
                except (TimeoutError, asyncio.TimeoutError):
                    pass
            if words and google.can_read_docs():
                try:
                    found = await asyncio.wait_for(google.docs(" ".join(words[-5:]), limit=1, timeout=2), 2.5)
                    past = past + [{"label": f"Google Doc {d['title']}", "text": d["text"][:600]} for d in found]
                except (TimeoutError, asyncio.TimeoutError):
                    pass
            calendar = await google.events(48)
            if calendar:
                past = past + [{"label": "calendar", "text": line[2:]} for line in google.describe(calendar).splitlines()]
            people = self.people + [c for c in await google.contacts()
                                    if not any(p["name"].lower() == c["name"].lower() for p in self.people)][:120]
            candidate = await brain.resolve(reason, self.lines, people, promises, past,
                                            born, prompted=prompted, interim=interim)
            if candidate:
                self._offer(candidate)
            else:
                await self._log(Candidate("ask" if prompted else "fact", "", 0.0, reason[:160],
                                          "", born, prompted), "declined")
        finally:
            if not prompted:
                self.resolving = False

    def _maybe_assist(self):
        """Every so often, with enough new talk, look for something worth stepping in with."""
        fresh = [line for line in self.lines[self.assisted_upto:] if not line.addressed and not line.retracted]
        gap = ASSIST_GAP_DEMO if self.governor.demo else ASSIST_GAP
        # Only in a conversation the owner is part of, and only about what someone else said:
        # a video playing nearby, or the owner's own words, are not moments to step in.
        if not any(line.who == "you" and not line.addressed and line.end > self.now - 120 for line in self.lines):
            return
        if not any(line.who != "you" for line in fresh):
            return
        if (self.assisting or self.pending or self.delivering or self.now - self.last_assist < gap
                or self.now < self.engaged_until or sum(len(line.text.split()) for line in fresh) < 5):
            return
        self.assisting, self.last_assist, self.assisted_upto = True, self.now, len(self.lines)
        task = asyncio.create_task(self._assist(self.now))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _assist(self, born: float):
        try:
            recent = " ".join(line.text for line in self.lines[-4:])
            words = [w for w in re.findall(r"[A-Za-z0-9]+", recent) if len(w) >= 4][-12:]
            memories, past = [], []
            try:
                memories = [m["text"] for m in await self.store.query("memories:list")]
                if words:
                    past = await self.store.query("conversations:search", text=" ".join(words),
                                                  exceptConversation=self.conversation, limit=8)
            except StoreError:
                pass
            if not memories and not past and not self.people:
                return
            candidate = await brain.assist(self.lines, memories, self.people, past, self.cues, born)
            if candidate and not self.ended:
                self.cues.append(candidate.text)
                self._offer(candidate)
        finally:
            self.assisting = False

    def _offer(self, candidate: Candidate):
        if candidate.key in self.governor.said:
            return
        current = self.pending
        if current and current.prompted and not candidate.prompted:
            return
        if current and current.key == candidate.key:
            return
        self.pending = candidate
        # The clip is made now, while waiting for a pause, so it can start the instant one comes.
        self.clips[candidate.key] = asyncio.create_task(tts.synthesize(candidate.text))

    # --- Whispering ----------------------------------------------------------------------

    async def _tick(self):
        now = self.now
        silence = now - self.last_speech
        if self.trail and not self.speaking and silence >= TRAIL_SILENCE:
            line, self.trail = self.trail, None
            self._trigger(f'the owner trailed off mid-sentence and went quiet: "{line.text}"')
        if self.asked and not self.speaking and silence >= ASKED_SILENCE:
            line, self.asked = self.asked, None
            self._trigger(
                f'{line.label} asked the owner a question and the owner has stayed silent: '
                f'"{line.text}". Speak only if the conversation or memory holds the specific answer'
            )

        if self.playing:
            whisper_id, candidate, began, until = self.playing
            if (self.speaking and self.speech_began > began + 0.1 and now - self.speech_began >= 0.6
                    and self._owner_is_speaking(self.speech_began, least=0.5)):
                self.playing = None
                self.governor.cut_off()
                await self.emit({"type": "stop_audio", "id": whisper_id})
                if whisper_id:
                    await self.store.mutation("whispers:setOutcome", id=whisper_id, outcome="cut")
            elif now >= until:
                self.playing = None
                self.governor.heard_in_full()

        if not self.speaking and silence >= 0.3 and self.lines:
            self._maybe_assist()  # talk that arrived while the last look was running gets its own look
        candidate = self.pending
        if candidate is None or self.delivering or self.playing:
            return
        if self.governor.stale(candidate, now):
            self.pending = None
            await self._log(candidate, "stale")
            return
        if self.speaking or silence < PAUSE_NEEDED.get(candidate.kind, 0.3):
            return
        self.pending = None
        outcome, reason = self.governor.decide(candidate, now)
        if outcome == "spoken":
            self.delivering = True
            task = asyncio.create_task(self._speak(candidate))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        else:
            candidate.why = f"{candidate.why} ({reason})"
            await self._log(candidate, outcome)

    async def _speak(self, candidate: Candidate):
        try:
            self.waiting = candidate
            ready = self.clips.pop(candidate.key, None)
            pcm = await ready if ready is not None else await tts.synthesize(candidate.text)
            # Someone may have started talking while the clip was being made: wait for a gap.
            while self.speaking or self.now - self.last_speech < 0.12:
                if self.governor.stale(candidate, self.now) or self.ended or candidate.key in self.answered:
                    await self._log(candidate, "stale")
                    return
                await asyncio.sleep(0.03)
            if candidate.key in self.answered:
                await self._log(candidate, "stale")
                return
            now = self.now
            self.governor.spoke(candidate, now)
            whisper_id = await self._log(candidate, "spoken", latency=now - candidate.born)
            self.playing = (whisper_id, candidate, now, now + len(pcm) / 2 / RATE)
            self.spoke.append((now, now + len(pcm) / 2 / RATE + 0.4))
            if candidate.prompted:
                self.engaged_until = now + len(pcm) / 2 / RATE + 20.0
            await self.emit({"type": "audio", "id": whisper_id, "pcm": pcm, "kind": candidate.kind,
                             "text": candidate.text})
        except Exception as error:  # noqa: BLE001 - a failed whisper is silence, plus a note
            await self.emit({"type": "error", "message": f"Whisper failed: {error}"})
        finally:
            self.delivering = False
            self.waiting = None

    async def _log(self, candidate: Candidate, outcome: str, latency: float | None = None):
        whisper_id = None
        try:
            whisper_id = await self.store.mutation(
                "whispers:log", conversationId=self.conversation, kind=candidate.kind,
                text=candidate.text, why=candidate.why, outcome=outcome,
                confidence=candidate.confidence, source=candidate.source or None,
                conversationSeconds=candidate.born,
                latencyMs=round(latency * 1000) if latency is not None else None,
            )
        except StoreError as error:
            await self.emit({"type": "error", "message": str(error)})
        await self.emit({
            "type": "whisper", "id": whisper_id, "kind": candidate.kind, "text": candidate.text,
            "why": candidate.why, "outcome": outcome, "confidence": candidate.confidence,
            "source": candidate.source, "at": candidate.born,
            "latency": latency,
        })
        return whisper_id

    def _introduced(self, label: str, name: str) -> bool:
        """Naming a voice is permanent, so the model's word is not enough: the speaker must
        have said who they are, or the owner must have addressed them by name."""
        first = re.escape(name.split()[0])
        own = re.compile(rf"\b(?:i'm|i am|my name is|my name's|call me|it's|this is)\s+{first}\b", re.I)
        address = re.compile(rf"(?:^|[.!?]\s+)(?:(?:hi|hey|hello|thanks|thank you|morning|good "
                             rf"morning|sorry|so|well|okay|ok),?\s+)?{first}\s*[,.!?]|,\s*{first}\s*[.!?]?$",
                             re.I)
        for index, line in enumerate(self.lines):
            if line.label == label and own.search(line.text):
                return True
            if line.who == "you" and address.search(line.text):
                others = {l.label for l in self.lines if l.who == "other"}
                if others == {label}:  # only one other voice, so the name can only be theirs
                    return True
        return False

    async def ask(self, text: str):
        """A typed or tapped question, answered like "Wingman, ..."."""
        self._trigger(f'the owner asked you directly: "{text}"', prompted=True)

    # --- Notes ---------------------------------------------------------------------------

    async def _extract(self):
        while self.unextracted:
            batch, self.unextracted = self.unextracted, []
            earlier = self.lines[: len(self.lines) - len(batch) - len(self.unextracted)]
            try:
                notes = await brain.extract(earlier, batch)
                await self._apply(notes, batch)
            except StoreError as error:
                await self.emit({"type": "error", "message": str(error)})

    async def _apply(self, notes: dict, batch: list[Line]):
        owner_name = next((p["name"].lower() for p in self.people if p.get("isOwner")), "")
        for person in notes["people"]:
            name = str(person["name"]).strip()
            if not name or name.lower() in (owner_name, "you", "wingman"):
                continue
            about = str(person.get("about") or "").strip() or None
            person_id = await self.store.mutation("people:upsert", name=name, about=about)
            await self.store.mutation("conversations:addPerson", id=self.conversation,
                                      personId=person_id)
            if not any(p["_id"] == person_id for p in self.people):
                self.people.append({"_id": person_id, "name": name, "about": about})
            await self.emit({"type": "person", "id": person_id, "name": name, "about": about})
            speaker = self.roster.by_label(str(person.get("speaker") or ""))
            if (speaker is not None and speaker.key.startswith("anon")
                    and self._introduced(speaker.label, name)):
                old = speaker.label
                self.roster.name(speaker.key, name, person_id)
                for line in self.lines:
                    if line.label == old:
                        line.label, line.person_id, line.who = name, person_id, "other"
                await self.store.mutation(
                    "conversations:relabel", conversationId=self.conversation,
                    fromLabel=old, label=name, who="other", personId=person_id,
                )
                await self.store.mutation(
                    "people:upsert", name=name, voiceprint=speaker.voiceprint.tolist(),
                    voiceSeconds=min(speaker.seconds, 120.0),
                )
                await self.emit({"type": "relabel", "from": old, "to": name})

        ids = {p["name"].lower(): p["_id"] for p in self.people}
        for promise in notes["promises"]:
            who = str(promise.get("person") or "").strip()
            speaker = self.roster.by_label(who)
            if speaker is not None:
                who = "" if speaker.key == "owner" else speaker.label
            what = str(promise["what"]).strip().rstrip(".")
            source = next((l for l in reversed(batch)
                           if l.who == ("you" if promise["by"] == "you" else "other")), None)
            if source is None:
                continue  # a promise must rest on a line by the right speaker
            promise_id = await self.store.mutation(
                "promises:add", conversationId=self.conversation, by=promise["by"],
                personId=ids.get(who.lower()), person=who or "someone", what=what,
                due=str(promise.get("due") or "").strip() or None,
                dueDate=str(promise.get("due_date") or "").strip() or None,
                lineId=source.id,
            )
            await self.emit({"type": "promise", "id": promise_id, "by": promise["by"],
                             "person": who or "someone", "what": what,
                             "due": promise.get("due") or ""})

        # A line spoken to Wingman was already answered, and acted on, by the agent.
        requests = [] if any(line.addressed for line in batch) else notes.get("requests")
        done = await actions.carry_out(self.store, requests, self.conversation)
        for task in done:
            await self.emit({"type": "task", **{k: v for k, v in task.items() if k != "clash"}})
        if done:
            self._offer(Candidate("ask", actions.confirmation(done), 1.0, "you asked Wingman to do this",
                                  "your request", self.now, prompted=True, key=f"task:{done[0]['id']}"))

        if notes["retract"]:
            mine = [line for line in self.lines if line.who == "you"]
            said = [line for line in batch if line.who == "you"]
            if said and said[-1] in mine:
                index = mine.index(said[-1])
                taken_back = mine[max(0, index - 1): index] or []
                for line in taken_back:
                    line.retracted = True
                ids_ = [line.id for line in taken_back if line.id]
                if ids_:
                    await self.store.mutation("conversations:retract", lineIds=ids_)
                    await self.emit({"type": "retracted", "ids": ids_})


def _meaning(text: str) -> set[str]:
    """The words that carry what a to-do or promise is about."""
    skip = {"the", "a", "an", "to", "with", "for", "of", "and", "on", "in", "at", "by", "my", "your", "about", "from",
            "send", "share", "email", "give", "get", "you", "them", "him", "her"}
    return {w.rstrip("s") if len(w) > 3 else w for w in re.findall(r"[a-z0-9]+", text.lower())} - skip


def _says(text: str, answer: str) -> bool:
    """Does this line already contain the answer Wingman was about to give."""
    wanted = re.sub(r"[^a-z0-9 ]", "", answer.lower()).strip()
    return bool(wanted) and wanted in re.sub(r"[^a-z0-9 ]", "", text.lower())
