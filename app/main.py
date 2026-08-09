"""FastAPI application for strict UTF-8, Unicode, and JSON analysis."""

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from starlette.responses import Response

from app.engine import (
    DETAIL_LIMIT,
    ENGINE_VERSION,
    RULESET_VERSION,
    UNICODE_VERSION,
    analyze_hidden,
)
from app.errors import (
    ALLOWED_ORIGINS,
    ApiProblem,
    error_response,
    json_response,
    method_not_allowed,
    request_id,
    response_headers,
)
from app.rate_limit import enforce_rate_limit
from app.schemas import (
    first_invalid_utf8_byte,
    read_envelope,
    validate_declared_envelope_size,
    validate_media_type,
)
from app.text_tools import count_text, inspect_code_points, validate_json
from app.unicode_review import check_normalization, detect_mojibake, review_mixed_scripts

logger = logging.getLogger("utf8_api")
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_PATHS = {
    "/favicon.svg": "favicon.svg",
    "/openapi.json": "openapi.json",
    "/swagger-ui.css": "swagger-ui.css",
    "/swagger-ui-bundle.js": "swagger-ui-bundle.js",
    "/swagger-ui-bundle.js.LICENSE.txt": "swagger-ui-bundle.js.LICENSE.txt",
    "/swagger-initializer.js": "swagger-initializer.js",
    "/swagger-ui.LICENSE.txt": "swagger-ui.LICENSE.txt",
    "/swagger-ui.NOTICE.txt": "swagger-ui.NOTICE.txt",
}
HTTP_METHODS = [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "TRACE",
    "CONNECT",
]
TOOL_PATHS = {
    "/v1/mojibake",
    "/v1/normalization",
    "/v1/mixed-script-confusables",
    "/v1/text-counts",
    "/v1/json-validation",
    "/v1/code-points",
}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _identifier(request: Request) -> str:
    identifier = getattr(request.state, "request_id", None)
    if identifier is None:
        identifier = request_id()
        request.state.request_id = identifier
    return identifier


@app.exception_handler(ApiProblem)
async def api_problem_handler(request: Request, problem: ApiProblem) -> Response:
    return error_response(problem, request, _identifier(request))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, _: Exception) -> Response:
    # Deliberately omit exception details: unexpected exceptions may contain input data.
    logger.error("Unhandled API request failure")
    return error_response(ApiProblem("internal_error", 500), request, _identifier(request))


def public_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": finding["id"],
        "rule": finding["rule"],
        "category": finding["category"],
        "severity": finding["severity"],
        "title": finding["title"],
        "location": finding["location"],
        "observed": finding["observed"],
        "explanation": finding["explanation"],
    }


def invalid_utf8_result(
    input_value: dict[str, Any], invalid_byte: int, identifier: str
) -> dict[str, Any]:
    return {
        "request_id": identifier,
        "status": "invalid_utf8",
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "unicode_version": UNICODE_VERSION,
        "input": {
            "kind": input_value["kind"],
            "bytes": len(input_value["bytes"]),
            "offset_basis": "submitted-bytes",
        },
        "encoding": {
            "valid_utf8": False,
            "basis": "submitted-bytes",
            "first_invalid_byte": invalid_byte,
        },
        "summary": {"total": 0, "returned": 0, "truncated": False},
        "findings": [],
        "skipped": [{"check": "hidden-characters", "reason": "invalid_utf8"}],
    }


def invalid_utf8_tool_result(
    input_value: dict[str, Any],
    invalid_byte: int,
    identifier: str,
    check: str,
) -> dict[str, Any]:
    return {
        "request_id": identifier,
        "status": "invalid_utf8",
        "engine_version": ENGINE_VERSION,
        "unicode_version": UNICODE_VERSION,
        "input": {
            "kind": input_value["kind"],
            "bytes": len(input_value["bytes"]),
            "offset_basis": "submitted-bytes",
        },
        "encoding": {
            "valid_utf8": False,
            "basis": "submitted-bytes",
            "first_invalid_byte": invalid_byte,
        },
        "skipped": [{"check": check, "reason": "invalid_utf8"}],
    }


def tool_result_base(
    input_value: dict[str, Any], text: str, identifier: str, status: str
) -> dict[str, Any]:
    counts = count_text(text)
    is_bytes = input_value["kind"] == "bytes"
    return {
        "request_id": identifier,
        "status": status,
        "engine_version": ENGINE_VERSION,
        "unicode_version": UNICODE_VERSION,
        "input": {
            "kind": input_value["kind"],
            "bytes": counts["utf8_bytes"],
            "utf16_code_units": counts["javascript_string_units"],
            "unicode_scalars": counts["unicode_scalars"],
            "lines": counts["lines"],
            "offset_basis": (
                "submitted-bytes" if is_bytes else "utf8-encoding-of-input-string"
            ),
        },
        "encoding": {
            "valid_utf8": True,
            "basis": (
                "submitted-bytes"
                if is_bytes
                else "strict-request-envelope-and-reencoded-text"
            ),
        },
    }


async def read_tool_text(
    request: Request, identifier: str, check: str
) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    if request.url.query:
        raise ApiProblem("invalid_request", 400)
    validate_media_type(request)
    validate_declared_envelope_size(request)
    await enforce_rate_limit(request)
    input_value = await read_envelope(request, allow_profile=False)
    if input_value["kind"] == "bytes":
        invalid_byte = first_invalid_utf8_byte(input_value["bytes"])
        if invalid_byte is not None:
            return (
                input_value,
                "",
                invalid_utf8_tool_result(input_value, invalid_byte, identifier, check),
            )
        text = input_value["bytes"].decode("utf-8", errors="strict")
    else:
        text = input_value["text"]
    return input_value, text, None


def successful_result(input_value: dict[str, Any], text: str, identifier: str) -> dict[str, Any]:
    analysis = analyze_hidden(text, input_value["profile"])
    is_bytes = input_value["kind"] == "bytes"
    return {
        "request_id": identifier,
        "status": "clean" if analysis["total"] == 0 else "issues_found",
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "unicode_version": UNICODE_VERSION,
        "profile": input_value["profile"],
        "input": {
            "kind": input_value["kind"],
            **analysis["metrics"],
            "offset_basis": "submitted-bytes" if is_bytes else "utf8-encoding-of-input-string",
        },
        "encoding": {
            "valid_utf8": True,
            "basis": (
                "submitted-bytes"
                if is_bytes
                else "strict-request-envelope-and-reencoded-text"
            ),
        },
        "summary": {
            "total": analysis["total"],
            "returned": len(analysis["findings"]),
            "truncated": analysis["total"] > DETAIL_LIMIT,
        },
        "findings": [public_finding(finding) for finding in analysis["findings"]],
    }


async def analyze_request(request: Request, identifier: str) -> dict[str, Any]:
    if request.url.query:
        raise ApiProblem("invalid_request", 400)
    validate_media_type(request)
    validate_declared_envelope_size(request)
    await enforce_rate_limit(request)
    input_value = await read_envelope(request)
    if input_value["kind"] == "bytes":
        invalid_byte = first_invalid_utf8_byte(input_value["bytes"])
        if invalid_byte is not None:
            return invalid_utf8_result(input_value, invalid_byte, identifier)
        text = input_value["bytes"].decode("utf-8", errors="strict")
    else:
        text = input_value["text"]
    return successful_result(input_value, text, identifier)


async def count_text_request(request: Request, identifier: str) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "text-counts"
    )
    if invalid_result is not None:
        return invalid_result
    return {
        **tool_result_base(input_value, text, identifier, "complete"),
        "counts": count_text(text),
    }


async def detect_mojibake_request(request: Request, identifier: str) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "mojibake"
    )
    if invalid_result is not None:
        return invalid_result
    analysis = detect_mojibake(text)
    return {
        **tool_result_base(
            input_value,
            text,
            identifier,
            "clean" if analysis["summary"]["total"] == 0 else "issues_found",
        ),
        "check": analysis["check"],
        "summary": analysis["summary"],
        "findings": analysis["findings"],
    }


async def check_normalization_request(
    request: Request, identifier: str
) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "normalization"
    )
    if invalid_result is not None:
        return invalid_result
    analysis = check_normalization(text)
    return {
        **tool_result_base(
            input_value,
            text,
            identifier,
            "normalized" if analysis["summary"]["total"] == 0 else "changes_found",
        ),
        "check": analysis["check"],
        "forms": analysis["forms"],
        "summary": analysis["summary"],
        "findings": analysis["findings"],
    }


async def review_mixed_scripts_request(
    request: Request, identifier: str
) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "mixed-script-confusables"
    )
    if invalid_result is not None:
        return invalid_result
    analysis = review_mixed_scripts(text)
    return {
        **tool_result_base(
            input_value,
            text,
            identifier,
            "issues_found" if analysis["review_recommended"] else "clean",
        ),
        "check": analysis["check"],
        "confusable_data": analysis["confusable_data"],
        "scripts": analysis["scripts"],
        "dominant_script": analysis["dominant_script"],
        "is_mixed_script": analysis["is_mixed_script"],
        "expected_script_combination": analysis["expected_script_combination"],
        "review_recommended": analysis["review_recommended"],
        "summary": analysis["summary"],
        "findings": analysis["findings"],
    }


async def validate_json_request(request: Request, identifier: str) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "json-validation"
    )
    if invalid_result is not None:
        return invalid_result
    validation = validate_json(text)
    return {
        **tool_result_base(
            input_value,
            text,
            identifier,
            "valid_json" if validation["valid"] else "invalid_json",
        ),
        **validation,
    }


async def inspect_code_points_request(
    request: Request, identifier: str
) -> dict[str, Any]:
    input_value, text, invalid_result = await read_tool_text(
        request, identifier, "code-points"
    )
    if invalid_result is not None:
        return invalid_result
    if len(text) > DETAIL_LIMIT:
        raise ApiProblem("input_too_large", 413)
    inspection = inspect_code_points(text)
    return {
        **tool_result_base(input_value, text, identifier, "complete"),
        **inspection,
    }


TOOL_HANDLERS = {
    "/v1/mojibake": detect_mojibake_request,
    "/v1/normalization": check_normalization_request,
    "/v1/mixed-script-confusables": review_mixed_scripts_request,
    "/v1/text-counts": count_text_request,
    "/v1/json-validation": validate_json_request,
    "/v1/code-points": inspect_code_points_request,
}


def preflight_response(request: Request, identifier: str) -> Response:
    origin = request.headers.get("origin")
    method = request.headers.get("access-control-request-method")
    requested_headers = [
        value.strip().lower()
        for value in request.headers.get("access-control-request-headers", "").split(",")
        if value.strip()
    ]
    if (
        origin not in ALLOWED_ORIGINS
        or method != "POST"
        or any(name != "content-type" for name in requested_headers)
    ):
        return error_response(ApiProblem("invalid_request", 400), request, identifier)
    return Response(
        content=None,
        status_code=204,
        headers={
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Max-Age": "600",
            "Cache-Control": "no-store",
            "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
            "X-Content-Type-Options": "nosniff",
            "X-Request-ID": identifier,
        },
    )


def static_response(request: Request, identifier: str, filename: str) -> Response:
    if request.method not in {"GET", "HEAD"}:
        return method_not_allowed(request, identifier, ["GET", "HEAD"])
    return FileResponse(STATIC_DIR / filename, headers=response_headers(request, identifier))


async def dispatch(request: Request) -> Response:
    identifier = _identifier(request)
    path = request.url.path

    if path == "/":
        return static_response(request, identifier, "index.html")
    if path in {"/docs", "/docs/"}:
        if request.method not in {"GET", "HEAD"}:
            return method_not_allowed(request, identifier, ["GET", "HEAD"])
        return Response(
            content=None,
            status_code=308,
            headers=response_headers(request, identifier, {"Location": "/"}),
        )
    if path in STATIC_PATHS:
        return static_response(request, identifier, STATIC_PATHS[path])
    if path == "/v1/health":
        if request.method != "GET":
            return method_not_allowed(request, identifier, ["GET"])
        if request.url.query:
            raise ApiProblem("invalid_request", 400)
        return json_response(
            {
                "status": "ok",
                "deployment": "api-v1",
                "engine_version": ENGINE_VERSION,
                "ruleset_version": RULESET_VERSION,
                "unicode_version": UNICODE_VERSION,
            },
            200,
            request,
            identifier,
        )
    if path == "/v1/hidden-characters":
        if request.method == "OPTIONS":
            return preflight_response(request, identifier)
        if request.method != "POST":
            return method_not_allowed(request, identifier, ["POST", "OPTIONS"])
        result = await analyze_request(request, identifier)
        return json_response(result, 200, request, identifier)
    if path in TOOL_PATHS:
        if request.method == "OPTIONS":
            return preflight_response(request, identifier)
        if request.method != "POST":
            return method_not_allowed(request, identifier, ["POST", "OPTIONS"])
        handler = TOOL_HANDLERS[path]
        result = await handler(request, identifier)
        return json_response(result, 200, request, identifier)
    return error_response(ApiProblem("invalid_request", 404), request, identifier)


app.add_api_route("/", dispatch, methods=HTTP_METHODS, include_in_schema=False)
app.add_api_route("/{path:path}", dispatch, methods=HTTP_METHODS, include_in_schema=False)
