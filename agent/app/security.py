"""Authentication tokens, rate limiting and request-origin checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, WebSocket

from app.config import Settings

WEAK_PINS = {"1234", "0000", "1111", "123456", "000000", "admin", "password", "change_me", ""}


def check_production_config(s: Settings) -> list[str]:
    """Return a list of blocking problems for APP_ENV=prod."""
    problems = []
    if s.staff_pin in WEAK_PINS or len(s.staff_pin) < 8:
        problems.append("STAFF_PIN must be at least 8 characters and not a common value")
    if s.postgres_password in WEAK_PINS or s.postgres_password in ("triage", "triage_demo_pw") or len(s.postgres_password) < 12:
        problems.append("POSTGRES_PASSWORD must be at least 12 characters and not a default")
    if len(s.secret_key) < 32:
        problems.append("SECRET_KEY must be set (32+ random characters)")
    return problems


class Tokens:
    """Stateless HMAC-signed staff tokens (no PIN ever travels in a URL)."""

    def __init__(self, secret: str, ttl: int):
        self.key = (secret or secrets.token_hex(32)).encode()
        self.ttl = ttl

    def issue(self, subject: str = "staff") -> str:
        body = base64.urlsafe_b64encode(json.dumps({"sub": subject, "exp": int(time.time()) + self.ttl}).encode()).decode().rstrip("=")
        sig = hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def verify(self, token: str | None) -> str | None:
        if not token or "." not in token:
            return None
        body, sig = token.rsplit(".", 1)
        good = hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except Exception:
            return None
        return data["sub"] if data.get("exp", 0) > time.time() else None


def pin_ok(given: str, real: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(real.encode()).digest())


class SlidingWindow:
    """N events per window per key. Memory-bounded (old keys are purged)."""

    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_purge = time.monotonic()

    def _purge(self, now: float) -> None:
        if now - self._last_purge < 60:
            return
        self._last_purge = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]:
            self.hits.pop(k, None)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._purge(now)
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def count(self, key: str) -> int:
        now = time.monotonic()
        q = self.hits.get(key)
        if not q:
            return 0
        while q and now - q[0] > self.window:
            q.popleft()
        return len(q)

    def blocked(self, key: str) -> bool:
        return self.count(key) >= self.limit

    def add(self, key: str) -> None:
        self.hits[key].append(time.monotonic())


def client_ip(conn: Request | WebSocket) -> str:
    """The reverse proxy (nginx) sets X-Real-IP; direct connections fall back to the socket address."""
    real = conn.headers.get("x-real-ip")
    if real and len(real) < 64:
        return real.strip()
    return conn.client.host if conn.client else "unknown"


def origin_allowed(ws: WebSocket, s: Settings) -> bool:
    """Reject cross-site WebSocket hijacking. Non-browser clients (no Origin) are allowed only in dev."""
    origin = ws.headers.get("origin")
    if not origin:
        return s.app_env != "prod"
    o = origin.rstrip("/")
    if o in s.origins:
        return True
    host = ws.headers.get("host", "")
    return bool(host) and o.split("://", 1)[-1] == host


def bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:] if h.lower().startswith("bearer ") else None


def require_staff(request: Request, tokens: Tokens) -> str:
    sub = tokens.verify(bearer(request))
    if not sub:
        raise HTTPException(status_code=401, detail="authentication required")
    return sub
