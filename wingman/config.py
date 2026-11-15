"""Settings read from the environment and the private .env file."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SAMPLE_RATE = 16000  # mono PCM16 everywhere: capture, speech-to-text and whisper playback

# A server in a data centre keeps time in UTC, but "at four", "today" and "this evening" mean
# the owner's clock. WINGMAN_TZ (for example America/Los_Angeles) sets the time zone all of
# Wingman's reckoning uses. One zone per server for now, not one per account.
if os.environ.get("WINGMAN_TZ"):
    os.environ["TZ"] = os.environ["WINGMAN_TZ"]
    time.tzset()

DATA_DIR = Path(os.environ.get("WINGMAN_DATA_DIR", ROOT / "data"))

SMALLEST_API_KEY = os.environ.get("SMALLEST_API_KEY", "")
SMALLEST_HOST = os.environ.get("SMALLEST_HOST", "api.smallest.ai")
STT_MODEL = os.environ.get("WINGMAN_STT_MODEL", "pulse")
TTS_MODEL = os.environ.get("WINGMAN_TTS_MODEL", "lightning_v3.1_pro")
TTS_VOICE = os.environ.get("WINGMAN_TTS_VOICE", "kaitlyn")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
GATE_MODEL = os.environ.get("WINGMAN_GATE_MODEL", "gpt-6-luna")
THINK_MODEL = os.environ.get("WINGMAN_THINK_MODEL", "gpt-6-luna")
# The agent the owner talks to: measured faster to its first word than the model above, and it
# does not reach for a tool when a plain answer will do.
# Nudges and explanations: the same fast model. Measured at about 0.9 s against 1.5 s, with the
# same decisions on when to speak and when to stay silent.
ASSIST_MODEL = os.environ.get("WINGMAN_ASSIST_MODEL", "gpt-5.4-mini")
AGENT_MODEL = os.environ.get("WINGMAN_AGENT_MODEL", "gpt-5.4-mini")


def require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set; add it to {ROOT / '.env'}")
    return value
