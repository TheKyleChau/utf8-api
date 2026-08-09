"""Per-process anonymous request limiting.

Operators should tune the constants for their deployment. This fixed-window
limiter is in-memory and per process: it resets at restart and does not
coordinate across replicas or containers.
"""

import asyncio
import base64
import hashlib
import hmac
import os
import re
import time
from collections import deque

from starlette.requests import Request

from app.errors import ApiProblem

RATE_LIMIT_MAX_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60

_LOCAL_HOST_RE = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_actor_requests: dict[str, deque[float]] = {}
_limiter_lock = asyncio.Lock()


def is_local_request(request: Request) -> bool:
    if os.environ.get("LOCAL_DEVELOPMENT") == "true":
        return True
    if request.url.hostname in {"localhost", "127.0.0.1", "::1", "[::1]"}:
        return True
    return _LOCAL_HOST_RE.fullmatch(request.headers.get("host", "").lower()) is not None


def anonymous_actor_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded is not None:
        first_entry = forwarded.split(",", 1)[0]
        if _CONTROL_RE.search(first_entry):
            raise ApiProblem("limiter_unavailable", 503)
        address = first_entry.strip(" ")
    else:
        address = request.client.host if request.client else ""

    secret = os.environ.get("API_RATE_LIMIT_HMAC_KEY")
    valid_secret = isinstance(secret, str) and len(secret) >= 32
    if (not address or not valid_secret) and is_local_request(request):
        address = address or "local-development"
        if not valid_secret:
            secret = "local-development-key-not-for-production"
            valid_secret = True

    if not address or not valid_secret or secret is None:
        raise ApiProblem("limiter_unavailable", 503)
    if len(address) > 64 or _CONTROL_RE.search(address):
        raise ApiProblem("limiter_unavailable", 503)

    digest = hmac.new(secret.encode(), address.encode(), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"hidden-v1:{encoded}"


async def enforce_rate_limit(request: Request) -> None:
    actor_key = anonymous_actor_key(request)
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    async with _limiter_lock:
        for key, timestamps in list(_actor_requests.items()):
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            if not timestamps:
                del _actor_requests[key]

        timestamps = _actor_requests.setdefault(actor_key, deque())
        if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            raise ApiProblem("rate_limited", 429, {"Retry-After": "60"})
        timestamps.append(now)
