"""In-memory registry of live portal sessions.

Why server-side sessions at all? The captcha answer lives in the portal's
PHP session (cookie) and the app_token rotates on every call, so the browser
that *shows* the captcha and the backend that *submits* the search must share
one cookie jar + token. We keep that jar here and give the frontend an opaque
session id.

Trade-off: in-memory means sessions vanish on restart and don't share across
multiple worker processes. That is acceptable because a portal session is
short-lived anyway (minutes), and the app is deployed as a single process.
If we ever scaled out, this would move to Redis with sticky routing.
"""
from __future__ import annotations

import os
import threading
import time

from .. import config
from .client import EcourtsClient
from .errors import SessionExpired

_sessions: dict[str, EcourtsClient] = {}
_lock = threading.Lock()


def _evict_locked(now: float) -> None:
    expired = [sid for sid, c in _sessions.items() if now - c.last_used > config.SESSION_TTL_SECONDS]
    for sid in expired:
        _sessions.pop(sid, None)
    # Hard cap: if somebody hammers "new session", drop the oldest first
    # rather than growing without bound.
    if len(_sessions) >= config.MAX_SESSIONS:
        for sid, _ in sorted(_sessions.items(), key=lambda kv: kv[1].last_used)[: len(_sessions) - config.MAX_SESSIONS + 1]:
            _sessions.pop(sid, None)


def create() -> tuple[str, EcourtsClient]:
    client = EcourtsClient()
    client.bootstrap()  # network call outside the global lock
    sid = os.urandom(16).hex()
    with _lock:
        _evict_locked(time.time())
        _sessions[sid] = client
    return sid, client


def get(sid: str) -> EcourtsClient:
    with _lock:
        _evict_locked(time.time())
        client = _sessions.get(sid)
    if client is None:
        raise SessionExpired("Your eCourts session has expired.",
                             hint="Start a new search; a fresh captcha will be loaded.")
    return client


def drop(sid: str) -> None:
    with _lock:
        _sessions.pop(sid, None)
