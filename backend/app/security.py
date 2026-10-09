"""Opaque server-side sessions: the browser never stores an authentication JWT.

CSRF headers protect cookie-authenticated mutations. The in-process throttler
limits local abuse; multiple production workers need a shared rate-limit store.
"""

import hashlib
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from argon2 import PasswordHasher
from fastapi import Depends, Header, HTTPException, Request
from .database import get_db
from .models import LoginSession, User
from .config import ALLOWED_ORIGINS

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("placeholder-password-for-timing")
_attempts = defaultdict(deque)
_lock = Lock()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def require_trusted_origin(request: Request):
    origin = request.headers.get("origin")
    # CLI/API clients do not supply Origin. JSON bodies plus a CSRF header are
    # still required for browser session mutations.
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, "This origin is not allowed to change account data.")


def throttle(request: Request):
    key = request.client.host if request.client else "unknown"
    now = time.time()
    with _lock:
        # Bound memory even when many independent clients attempt authentication.
        for old_key in list(_attempts):
            if not _attempts[old_key] or _attempts[old_key][-1] <= now - 300:
                del _attempts[old_key]
        bucket = _attempts[key]
        while bucket and bucket[0] <= now - 300:
            bucket.popleft()
        if len(bucket) >= 20:
            raise HTTPException(
                429, "Too many account attempts. Try again in five minutes.", headers={"Retry-After": "300"}
            )
        bucket.append(now)


def current_user(request: Request, x_csrf_token: str | None = Header(default=None), db=Depends(get_db)):
    token = request.cookies.get("strategy_session", "")
    session = db.get(LoginSession, digest(token)) if token else None
    if session is None or session.expires_at <= time.time():
        raise HTTPException(401, "Sign in to access your business analyses.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_trusted_origin(request)
        supplied = x_csrf_token or ""
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(403, "The security token is missing or expired. Refresh and try again.")
    request.state.login_session = session
    return db.get(User, session.user_id)
