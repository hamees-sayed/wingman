"""Who a request, a listening session or a background job is working for.

Wingman began as one person's assistant. Now each install has its own account, and everything
kept about a person (their memory, their sign-ins, their caches) is kept apart from everyone
else's. The account in force is carried in a context variable, so code deep inside an
integration never has to be handed it: the database client stamps it on every call, and the
files and caches below resolve to that person's own.

The first owner's data predates accounts and is filed under "owner". It stays where it was
(the top of the data folder, rows with no user) so nothing has to move.
"""

import contextvars
import hashlib
import hmac
import json
import os
from pathlib import Path

from wingman import config

OWNER = "owner"
current: contextvars.ContextVar[str] = contextvars.ContextVar("wingman_user", default=OWNER)
_CLAIM = config.DATA_DIR / "owner-claim.json"  # which account the first owner's data now belongs to


def user() -> str:
    return current.get()


def become(who: str):
    """Work as this account from here on, in this request or task and the tasks it starts."""
    return current.set(who)


def _digest(token: str) -> str:
    return hashlib.sha256(("account:" + token).encode()).hexdigest()


def _claimed() -> str | None:
    try:
        return json.loads(_CLAIM.read_text()).get("account")
    except (OSError, ValueError):
        return None


def resolve(token: str | None) -> str | None:
    """The account an app's token stands for, or None when it may not be let in.

    No token is how installs from before accounts speak; they are the first owner, until that
    owner's data has been claimed by a proper account, after which a token is always needed."""
    token = (token or "").strip()
    claimed = _claimed()
    if not token:
        return None if claimed else OWNER
    if len(token) < 24:
        return None
    digest = _digest(token)
    return OWNER if digest == claimed else "u" + digest[:24]


def claim_owner(token: str) -> bool:
    """Hand the first owner's data to this account. Works once."""
    token = (token or "").strip()
    if _claimed() or len(token) < 24:
        return _claimed() == _digest(token)
    _CLAIM.parent.mkdir(parents=True, exist_ok=True)
    _CLAIM.write_text(json.dumps({"account": _digest(token)}))
    _CLAIM.chmod(0o600)
    return True


def sign(text: str) -> str:
    """A short signature, for values that leave the server and come back (sign-in round trips)."""
    key = os.environ.get("WINGMAN_KEY", "")
    return hmac.new(key.encode(), text.encode(), hashlib.sha256).hexdigest()[:24]


def stamp() -> str:
    """The current account as a value that can go out in a sign-in link and be trusted on return."""
    who = user()
    return f"{who}.{sign('state:' + who)}"


def from_stamp(value: str | None) -> str | None:
    who, _, signature = (value or "").partition(".")
    return who if who and hmac.compare_digest(signature, sign("state:" + who)) else None


def folder() -> Path:
    """Where this account's own files live."""
    who = user()
    if who == OWNER:
        return config.DATA_DIR
    path = config.DATA_DIR / "users" / who
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


class File:
    """A file that every account has its own copy of. Used like a Path."""

    def __init__(self, name: str):
        self.name = name

    def _path(self) -> Path:
        return folder() / self.name

    def __getattr__(self, attribute):
        return getattr(self._path(), attribute)

    def __fspath__(self) -> str:
        return str(self._path())


class Scoped:
    """A dict, list or set that every account has its own copy of. Used like the thing itself."""

    def __init__(self, make):
        self._make, self._all = make, {}

    def _mine(self):
        who = user()
        if who not in self._all:
            self._all[who] = self._make()
        return self._all[who]

    def __getattr__(self, attribute):
        return getattr(self._mine(), attribute)

    def __getitem__(self, key):
        return self._mine()[key]

    def __setitem__(self, key, value):
        self._mine()[key] = value

    def __delitem__(self, key):
        del self._mine()[key]

    def __contains__(self, key):
        return key in self._mine()

    def __iter__(self):
        return iter(self._mine())

    def __len__(self):
        return len(self._mine())

    def __bool__(self):
        return bool(self._mine())


class Value:
    """A single cached value that every account has its own copy of."""

    def __init__(self, default=None):
        self._default, self._all = default, {}

    def get(self):
        return self._all.get(user(), self._default)

    def set(self, value):
        self._all[user()] = value
