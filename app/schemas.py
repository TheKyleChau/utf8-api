"""Strict request-envelope parsing and byte validation."""

import base64
import binascii
import json
import re
from typing import Any

from starlette.requests import Request

from app.engine import contains_unpaired_surrogate
from app.errors import ApiProblem

ENVELOPE_LIMIT_BYTES = 256 * 1024
INPUT_LIMIT_BYTES = 32 * 1024
ALLOWED_PROFILES = {"general", "identifier"}

_BASE64_RE = re.compile(
    r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
)
_CONTENT_LENGTH_RE = re.compile(r"^(?:0|[1-9]\d*)$")
_CONTENT_TYPE_RE = re.compile(
    r'^application/json(?:\s*;\s*charset\s*=\s*(?:"utf-8"|utf-8))?\s*$',
    re.IGNORECASE,
)


def has_exact_keys(
    value: object,
    required: set[str],
    optional: set[str] | None = None,
) -> bool:
    if not isinstance(value, dict):
        return False
    allowed = required | (optional or set())
    return required.issubset(value) and set(value).issubset(allowed)


def decode_canonical_base64(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or len(value) % 4 != 0
        or _BASE64_RE.fullmatch(value) is None
    ):
        raise ApiProblem("invalid_base64", 400)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ApiProblem("invalid_base64", 400) from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ApiProblem("invalid_base64", 400)
    return decoded


def first_invalid_utf8_byte(data: bytes) -> int | None:
    def continuation(index: int) -> bool:
        return 0x80 <= data[index] <= 0xBF

    index = 0
    while index < len(data):
        first = data[index]
        if first <= 0x7F:
            index += 1
            continue
        if 0xC2 <= first <= 0xDF:
            if index + 1 >= len(data):
                return index
            if not continuation(index + 1):
                return index + 1
            index += 2
            continue
        if 0xE0 <= first <= 0xEF:
            if index + 1 >= len(data):
                return index
            second = data[index + 1]
            if first == 0xE0:
                valid_second = 0xA0 <= second <= 0xBF
            elif first == 0xED:
                valid_second = 0x80 <= second <= 0x9F
            else:
                valid_second = 0x80 <= second <= 0xBF
            if not valid_second:
                return index + 1
            if index + 2 >= len(data):
                return index
            if not continuation(index + 2):
                return index + 2
            index += 3
            continue
        if 0xF0 <= first <= 0xF4:
            if index + 1 >= len(data):
                return index
            second = data[index + 1]
            if first == 0xF0:
                valid_second = 0x90 <= second <= 0xBF
            elif first == 0xF4:
                valid_second = 0x80 <= second <= 0x8F
            else:
                valid_second = 0x80 <= second <= 0xBF
            if not valid_second:
                return index + 1
            if index + 2 >= len(data):
                return index
            if not continuation(index + 2):
                return index + 2
            if index + 3 >= len(data):
                return index
            if not continuation(index + 3):
                return index + 3
            index += 4
            continue
        return index
    return None


def validate_envelope(value: object, *, allow_profile: bool = True) -> dict[str, Any]:
    optional_keys = {"profile"} if allow_profile else set()
    if not has_exact_keys(value, {"input"}, optional_keys):
        raise ApiProblem("invalid_request", 400)
    assert isinstance(value, dict)
    profile = value.get("profile", "general")
    if not isinstance(profile, str) or profile not in ALLOWED_PROFILES:
        raise ApiProblem("unsupported_profile", 400)
    input_value = value["input"]
    if not isinstance(input_value, dict):
        raise ApiProblem("invalid_request", 400)

    if input_value.get("kind") == "text":
        text = input_value.get("value")
        if (
            not has_exact_keys(input_value, {"kind", "value"})
            or not isinstance(text, str)
            or contains_unpaired_surrogate(text)
        ):
            raise ApiProblem("invalid_request", 400)
        encoded = text.encode("utf-8")
        if len(encoded) > INPUT_LIMIT_BYTES:
            raise ApiProblem("input_too_large", 413)
        return {"kind": "text", "profile": profile, "text": text, "bytes": encoded}

    if input_value.get("kind") == "bytes":
        if (
            not has_exact_keys(input_value, {"kind", "base64", "declared_charset"})
            or input_value.get("declared_charset") != "utf-8"
        ):
            raise ApiProblem("invalid_request", 400)
        decoded = decode_canonical_base64(input_value.get("base64"))
        if len(decoded) > INPUT_LIMIT_BYTES:
            raise ApiProblem("input_too_large", 413)
        return {"kind": "bytes", "profile": profile, "bytes": decoded}

    raise ApiProblem("invalid_request", 400)


def validate_media_type(request: Request) -> None:
    if "content-encoding" in request.headers:
        raise ApiProblem("unsupported_content_encoding", 415)
    content_type = request.headers.get("content-type", "")
    if _CONTENT_TYPE_RE.fullmatch(content_type) is None:
        raise ApiProblem("unsupported_media_type", 415)


def parse_content_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    if value is None:
        return None
    if _CONTENT_LENGTH_RE.fullmatch(value) is None:
        raise ApiProblem("invalid_request", 400)
    length = int(value)
    if length > (2**53 - 1):
        raise ApiProblem("input_too_large", 413)
    return length


def validate_declared_envelope_size(request: Request) -> None:
    declared = parse_content_length(request)
    if declared is not None and declared > ENVELOPE_LIMIT_BYTES:
        raise ApiProblem("input_too_large", 413)


def _reject_json_constant(_: str) -> None:
    raise ValueError


async def read_envelope(
    request: Request, *, allow_profile: bool = True
) -> dict[str, Any]:
    validate_media_type(request)
    validate_declared_envelope_size(request)
    chunks: list[bytes] = []
    body_length = 0
    async for chunk in request.stream():
        body_length += len(chunk)
        if body_length > ENVELOPE_LIMIT_BYTES:
            raise ApiProblem("input_too_large", 413)
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        # TextDecoder's default BOM handling removes one leading UTF-8 BOM.
        source = body.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise ApiProblem("invalid_envelope_utf8", 400) from None
    try:
        parsed = json.loads(source, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        raise ApiProblem("invalid_request", 400) from None
    return validate_envelope(parsed, allow_profile=allow_profile)
