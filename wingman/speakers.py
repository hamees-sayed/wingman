"""Who is speaking: voiceprints, and splitting transcribed words by speaker.

Pulse's own speaker labels are not enabled on this account, so separation is done here.
Each sentence's audio is turned into a voice embedding and matched against the people
Wingman knows (the owner and anyone named before) and against the unnamed speakers heard
so far in this conversation.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import sherpa_onnx

from wingman import config
from wingman.stt import Word

MODEL = config.ROOT / "models" / "nemo_en_titanet_small.onnx"

# Cosine similarity between two clips of the same voice: 0.68 and up on clean three-second
# clips, but a real voice through a phone microphone measured 0.48 to 0.81 against its
# enrolment, lower on short sentences. Different real voices sit well under 0.4.
SAME_VOICE = 0.45
SAME_VOICE_SHORT = 0.38  # for clips under SHORT_SECONDS, against people already known
SHORT_SECONDS = 1.5
MIN_SECONDS = 0.35  # below this a clip says too little about the voice
LEARN_FROM = 0.62  # only confident matches refine a voiceprint
# The owner is the voice heard most and the one whose words are acted on, and their match
# against enrolment swings widely on a phone (measured 0.39 to 0.59 minutes after enrolling).
# Other real voices score under 0.1 against them. So a clip that resembles the owner this
# much is the owner, unless a person known by name fits it better.
OWNER_FLOOR = 0.30
OWNER_OVER_UNNAMED = 0.20  # an unnamed voice must beat the owner by this much to be someone else


@dataclass
class Speaker:
    key: str  # "owner", a person id, or "anon-2"
    who: str  # you | other | unknown
    label: str  # You, a name, Speaker 2
    person_id: str | None = None
    total: np.ndarray | None = None  # sum of unit embeddings, weighted by seconds
    seconds: float = 0.0
    session_seconds: float = 0.0  # speech heard in this conversation

    @property
    def voiceprint(self) -> np.ndarray | None:
        if self.total is None:
            return None
        return self.total / (np.linalg.norm(self.total) or 1.0)


UNKNOWN = Speaker(key="unknown", who="unknown", label="Unknown")


class Embedder:
    def __init__(self):
        if not MODEL.exists():
            raise SystemExit(f"Voice model missing: {MODEL}")
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=2)
        )

    def embed(self, pcm: bytes) -> np.ndarray:
        stream = self.extractor.create_stream()
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        stream.accept_waveform(config.SAMPLE_RATE, samples)
        stream.input_finished()
        vector = np.array(self.extractor.compute(stream), dtype=np.float64)
        return vector / (np.linalg.norm(vector) or 1.0)


@dataclass
class Roster:
    """The voices in play: known people first, then unnamed speakers of this conversation."""

    speakers: dict[str, Speaker] = field(default_factory=dict)
    next_anon: int = 2

    @classmethod
    def from_people(cls, people: list[dict]) -> "Roster":
        roster = cls()
        for person in people:
            vector = np.array(person["voiceprint"], dtype=np.float64)
            seconds = float(person.get("voiceSeconds") or 10.0)
            owner = bool(person.get("isOwner"))
            key = "owner" if owner else person["_id"]
            roster.speakers[key] = Speaker(
                key=key,
                who="you" if owner else "other",
                label="You" if owner else person["name"],
                person_id=person["_id"],
                total=vector * seconds,
                seconds=seconds,
            )
        return roster

    @property
    def has_owner(self) -> bool:
        return "owner" in self.speakers

    def score(self, vector: np.ndarray) -> list[tuple[float, Speaker]]:
        scored = [
            (float(vector @ speaker.voiceprint), speaker)
            for speaker in self.speakers.values()
            if speaker.total is not None
        ]
        return sorted(scored, key=lambda pair: -pair[0])

    def identify(self, vector: np.ndarray, seconds: float) -> tuple[Speaker, float]:
        """The speaker this clip belongs to, creating an unnamed one for a new voice."""
        scored = self.score(vector)
        best_score, best = scored[0] if scored else (0.0, None)
        short = seconds < SHORT_SECONDS
        print(f"voice: {seconds:.1f}s " + ", ".join(f"{sp.label}={sc:.2f}" for sc, sp in scored[:4]), flush=True)
        owner = next(((sc, sp) for sc, sp in scored if sp.key == "owner"), None)
        if owner is not None and owner[1] is not best and owner[0] >= OWNER_FLOOR:
            # An unnamed "Speaker 2" is often the owner's own voice from one bad clip.
            named = best.person_id is not None
            if (named and best_score - owner[0] < 0.05) or (not named and best_score - owner[0] < OWNER_OVER_UNNAMED):
                best_score, best = owner
        if best is not None and best.key == "owner" and best_score >= OWNER_FLOOR:
            best.session_seconds += seconds
            if best_score >= LEARN_FROM and not short:
                best.total = best.total + vector * seconds
                best.seconds += seconds
            return best, best_score
        if best is not None and best_score >= (SAME_VOICE_SHORT if short else SAME_VOICE):
            # A short clip must also clearly prefer this voice over the runner-up.
            if not short or len(scored) < 2 or best_score - scored[1][0] >= 0.08:
                best.session_seconds += seconds
                if best_score >= LEARN_FROM and not short:
                    best.total = best.total + vector * seconds
                    best.seconds += seconds
                return best, best_score
        # A short clip only starts a new speaker when it is clearly unlike every known voice.
        if short and not (seconds >= 0.9 and best_score < 0.25):
            return UNKNOWN, best_score
        speaker = Speaker(
            key=f"anon-{self.next_anon}",
            who="other" if self.has_owner else "unknown",
            label=f"Speaker {self.next_anon}",
            total=vector * seconds,
            seconds=seconds,
            session_seconds=seconds,
        )
        self.next_anon += 1
        self.speakers[speaker.key] = speaker
        return speaker, 1.0

    def name(self, key: str, name: str, person_id: str) -> Speaker | None:
        """An unnamed speaker turned out to be this person."""
        speaker = self.speakers.get(key)
        if speaker is None or speaker.key == "owner":
            return None
        speaker.label, speaker.person_id, speaker.who = name, person_id, "other"
        return speaker

    def by_label(self, label: str) -> Speaker | None:
        wanted = label.strip().lower()
        return next((s for s in self.speakers.values() if s.label.lower() == wanted), None)


@dataclass(frozen=True)
class Attributed:
    speaker: Speaker
    text: str
    start: float
    end: float
    confidence: float


def sentences(words: list[Word]) -> list[list[Word]]:
    """Speakers almost always change at a sentence end, so that is where words are cut."""
    out, run = [], []
    for word in words:
        run.append(word)
        if word.text.rstrip("\"')").endswith((".", "?", "!")):
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def attribute(
    words: list[Word],
    audio: Callable[[float, float], bytes],
    embedder: Embedder,
    roster: Roster,
) -> list[Attributed]:
    """Split one finished stretch of words into runs by speaker."""
    judged: list[tuple[list[Word], Speaker | None, float]] = []
    for sentence in sentences(words):
        start, end = sentence[0].start, sentence[-1].end
        seconds = end - start
        if seconds < MIN_SECONDS:
            judged.append((sentence, None, 0.0))
            continue
        speaker, score = roster.identify(embedder.embed(audio(start - 0.1, end + 0.1)), seconds)
        judged.append((sentence, None if speaker is UNKNOWN else speaker, score))

    # Sentences that could not be judged alone are judged together: two short sentences by
    # a new voice are long enough between them to recognise it.
    index = 0
    while index < len(judged):
        if judged[index][1] is not None:
            index += 1
            continue
        last = index
        while last + 1 < len(judged) and judged[last + 1][1] is None:
            last += 1
        start, end = judged[index][0][0].start, judged[last][0][-1].end
        if last > index and end - start >= MIN_SECONDS:
            speaker, score = roster.identify(
                embedder.embed(audio(start - 0.1, end + 0.1)), end - start
            )
            if speaker is not UNKNOWN:
                for position in range(index, last + 1):
                    judged[position] = (judged[position][0], speaker, score)
        index = last + 1

    # A sentence too short to judge goes with its neighbour in the same stretch.
    for index, (sentence, speaker, score) in enumerate(judged):
        if speaker is None:
            before = judged[index - 1][1] if index > 0 else None
            after = next((s for _, s, _ in judged[index + 1 :] if s is not None), None)
            neighbour = before or after
            judged[index] = (sentence, neighbour, 0.3 if neighbour else 0.0)

    runs: list[Attributed] = []
    for sentence, speaker, score in judged:
        speaker = speaker or UNKNOWN
        text = " ".join(word.text for word in sentence)
        if runs and runs[-1].speaker is speaker:
            last = runs[-1]
            runs[-1] = Attributed(speaker, f"{last.text} {text}", last.start, sentence[-1].end,
                                  min(last.confidence, score))
        else:
            runs.append(Attributed(speaker, text, sentence[0].start, sentence[-1].end, score))
    return runs
