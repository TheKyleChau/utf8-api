"""API error types and response helpers."""

import json
import uuid
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

ALLOWED_ORIGINS = {"https://utf8.ai", "https://www.utf8.ai"}

ERROR_MESSAGES = {
    "invalid_request": "The request body does not match the API contract.",
    "invalid_envelope_utf8": "The JSON request body is not valid UTF-8.",
    "invalid_base64": "The byte input is not canonical standard Base64.",
    "input_too_large": "The request or decoded input exceeds its size limit.",
    "unsupported_profile": "The requested analysis profile is not supported.",
    "unsupported_media_type": "Content-Type must be application/json.",
    "unsupported_content_encoding": "Content-Encoding is not supported.",
    "rate_limited": "The anonymous API rate limit has been reached.",
    "limiter_unavailable": "The anonymous API limiter is unavailable.",
    "internal_error": "The API could not complete the request.",
}


class ApiProblem(Exception):
    def __init__(
        self,
        code: str,
        status: int,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.headers = dict(headers or {})


def request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def response_headers(
    request: Request,
    identifier: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Request-ID": identifier,
    }
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Expose-Headers": "X-Request-ID",
                "Vary": "Origin",
            }
        )
    if extra:
        headers.update(extra)
    return headers


def json_response(
    body: Any,
    status: int,
    request: Request,
    identifier: str,
    extra: Mapping[str, str] | None = None,
) -> Response:
    content = (json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    headers = response_headers(request, identifier, extra)
    headers["Content-Type"] = "application/json; charset=utf-8"
    return Response(content=content, status_code=status, headers=headers)


def error_response(problem: ApiProblem, request: Request, identifier: str) -> Response:
    known = problem.code in ERROR_MESSAGES
    code = problem.code if known else "internal_error"
    status = problem.status if known else 500
    return json_response(
        {
            "error": {
                "code": code,
                "message": ERROR_MESSAGES[code],
                "request_id": identifier,
            }
        },
        status,
        request,
        identifier,
        problem.headers,
    )


def method_not_allowed(request: Request, identifier: str, allowed: list[str]) -> Response:
    return error_response(
        ApiProblem("invalid_request", 405, {"Allow": ", ".join(allowed)}),
        request,
        identifier,
    )
