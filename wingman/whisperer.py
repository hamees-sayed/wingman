"""The rules every whisper must pass, whatever the model recommends."""

from dataclasses import dataclass, field

from wingman.brain import Candidate


@dataclass(frozen=True)
class Policy:
    speak_bar: float  # confidence needed to be spoken
    card_bar: float  # confidence needed to be shown silently instead
    spacing: float  # seconds between unprompted whispers
    backoff: bool  # double the spacing each time the owner talks over one


POLICIES = {
    "quiet": Policy(speak_bar=0.8, card_bar=0.55, spacing=120.0, backoff=True),
    "normal": Policy(speak_bar=0.6, card_bar=0.4, spacing=60.0, backoff=True),
}
# For a short demo: several whispers in ninety seconds, and no penalty for talking over one.
DEMO_SPACING = 8.0

STALE_AFTER = 6.0  # a name that arrives later than this is no longer wanted
STALE_AFTER_ASKED = 12.0
# How long nobody must have been speaking before a whisper starts.
STALE_AFTER_CUE = 9.0  # a nudge or an explanation is still useful a little later
PAUSE_NEEDED = {"name": 0.25, "fact": 0.25, "ask": 0.2, "promise": 0.7, "nudge": 0.25, "explain": 0.25, "brief": 0.3}


@dataclass
class Governor:
    eagerness: str = "normal"
    demo: bool = False
    last_spoken: float | None = None
    talked_over: int = 0
    said: set[str] = field(default_factory=set)
    bar_shift: dict[str, float] = field(default_factory=dict)  # per kind, from the owner's grades

    @property
    def policy(self) -> Policy:
        return POLICIES.get(self.eagerness, POLICIES["normal"])

    def spacing(self) -> float:
        if self.demo:
            return DEMO_SPACING
        policy = self.policy
        return policy.spacing * (2 ** self.talked_over if policy.backoff else 1)

    def stale(self, candidate: Candidate, now: float) -> bool:
        limit = STALE_AFTER_ASKED if candidate.prompted else STALE_AFTER
        if candidate.kind in ("nudge", "explain", "brief"):
            limit = STALE_AFTER_CUE
        return now - candidate.born > limit

    def decide(self, candidate: Candidate, now: float) -> tuple[str, str]:
        """Returns (spoken | card | held, reason)."""
        if candidate.key in self.said:
            return "held", "already said"
        if candidate.prompted:
            return "spoken", "you asked"
        bar = self.policy.speak_bar + self.bar_shift.get(candidate.kind, 0.0)
        if candidate.confidence < self.policy.card_bar:
            return "held", f"confidence {candidate.confidence:.2f} too low"
        if candidate.confidence < bar:
            return "card", f"confidence {candidate.confidence:.2f} below {bar:.2f}"
        if self.last_spoken is not None and now - self.last_spoken < self.spacing():
            return "card", "too soon after the last whisper"
        return "spoken", "admitted"

    def spoke(self, candidate: Candidate, now: float):
        self.said.add(candidate.key)
        if not candidate.prompted:
            self.last_spoken = now

    def heard_in_full(self):
        self.talked_over = 0

    def cut_off(self):
        if not self.demo:
            self.talked_over += 1

    def learn(self, grades: dict[str, dict[str, int]]):
        """Thumbs down raise the bar for that kind of whisper; thumbs up lower it a little."""
        for kind, tally in grades.items():
            shift = 0.05 * (tally.get("down", 0) - 0.5 * tally.get("up", 0))
            self.bar_shift[kind] = max(-0.1, min(0.25, shift))
