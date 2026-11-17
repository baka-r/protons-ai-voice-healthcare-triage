"""Provider/key routing with automatic fallback.

Each (provider, key, model) is a Route. A route that fails for an auth reason is disabled for
the rest of the process; one that is rate limited / timing out is put on a cooldown. Callers
simply try the available routes in order, so a full free-tier key quietly shifts traffic to the
next key, then the next provider, without any request failing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("routing")


@dataclass
class Route:
    name: str  # safe to log/show: never contains the key
    provider: str  # openai | groq | local
    key: str = field(default="", repr=False)
    model: str = ""
    effort: str | None = None
    disabled: bool = False
    disabled_reason: str = ""
    cooldown_until: float = 0.0
    ok_count: int = 0
    fail_count: int = 0

    def available(self) -> bool:
        return not self.disabled and time.monotonic() >= self.cooldown_until

    def state(self) -> str:
        if self.disabled:
            return f"disabled ({self.disabled_reason})"
        left = self.cooldown_until - time.monotonic()
        return f"cooldown {int(left)}s" if left > 0 else "ok"


def classify_exception(exc: BaseException) -> tuple[str, float]:
    """Map an SDK/httpx exception to (kind, cooldown_seconds). kind: auth|rate|timeout|net|server|bad_request|other."""
    try:
        import openai
    except Exception:  # pragma: no cover
        openai = None  # type: ignore[assignment]
    if openai is not None:
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return "auth", 0
        if isinstance(exc, openai.RateLimitError):
            if getattr(exc, "code", None) == "insufficient_quota":
                return "quota", 3600
            return "rate", _retry_after(getattr(exc, "response", None), 60)
        if isinstance(exc, openai.APITimeoutError):
            return "timeout", 15
        if isinstance(exc, openai.APIConnectionError):
            return "net", 15
        if isinstance(exc, openai.InternalServerError):
            return "server", 30
        if isinstance(exc, (openai.BadRequestError, openai.NotFoundError, openai.UnprocessableEntityError)):
            return "bad_request", 300
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout", 15
    if isinstance(exc, httpx.TransportError):
        return "net", 15
    return "other", 20


def classify_status(status: int, headers: httpx.Headers | None = None) -> tuple[str, float]:
    if status in (401, 403):
        return "auth", 0
    if status == 429:
        return "rate", _retry_after_headers(headers, 60)
    if status >= 500:
        return "server", 30
    if status in (400, 404, 422):
        return "bad_request", 300
    return "other", 20


def _retry_after_headers(headers, default: float) -> float:
    try:
        v = headers.get("retry-after") if headers is not None else None
        return max(1.0, min(float(v), 3600.0)) if v else default
    except (TypeError, ValueError):
        return default


def _retry_after(resp, default: float) -> float:
    return _retry_after_headers(getattr(resp, "headers", None), default)


def record_failure(route: Route, routes: list[Route], kind: str, cooldown: float) -> None:
    route.fail_count += 1
    if kind == "auth":
        # the key itself is bad: every route that shares provider+key is dead
        for r in routes:
            if r.provider == route.provider and r.key == route.key:
                if not r.disabled:
                    log.warning("route %s disabled: authentication failed", r.name)
                r.disabled, r.disabled_reason = True, "auth failed"
        return
    route.cooldown_until = time.monotonic() + max(cooldown, 1.0)
    log.warning("route %s cooling down %ds (%s)", route.name, int(cooldown), kind)


def rotate_groups(routes: list[Route], offset: int) -> list[Route]:
    """Keep provider/model priority, but round-robin the keys inside each (provider, model) group."""
    out: list[Route] = []
    i = 0
    while i < len(routes):
        j = i
        while j < len(routes) and (routes[j].provider, routes[j].model) == (routes[i].provider, routes[i].model):
            j += 1
        group = routes[i:j]
        k = offset % len(group)
        out.extend(group[k:] + group[:k])
        i = j
    return out


def snapshot(routes: list[Route]) -> list[dict]:
    return [{"route": r.name, "state": r.state(), "ok": r.ok_count, "failed": r.fail_count} for r in routes]
