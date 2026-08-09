import base64
import json
import re
from typing import Any

import pytest
from fastapi.openapi.models import OpenAPI
from fastapi.testclient import TestClient

import app.main as main_module
import app.rate_limit as rate_limit
from app.engine import DETAIL_LIMIT, ENGINE_VERSION, RULESET_VERSION, UNICODE_VERSION
from app.main import TOOL_PATHS as IMPLEMENTED_TOOL_PATHS
from app.main import app
from scripts.generate_openapi import build_document

SECRET = "test-rate-limit-hmac-key-32-bytes-minimum"
ACTOR_HEADERS = {"X-Forwarded-For": "192.0.2.10"}
REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{32}$")
TOOL_PATHS = [
    "/v1/mojibake",
    "/v1/normalization",
    "/v1/mixed-script-confusables",
    "/v1/text-counts",
    "/v1/json-validation",
    "/v1/code-points",
]


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_HMAC_KEY", SECRET)
    monkeypatch.delenv("LOCAL_DEVELOPMENT", raising=False)
    rate_limit._actor_requests.clear()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app, base_url="https://api.utf8.ai") as test_client:
        yield test_client


def post_json(
    client: TestClient,
    value: object,
    *,
    path: str = "/v1/hidden-characters",
    **kwargs: object,
):
    headers = {"Content-Type": "application/json", **ACTOR_HEADERS}
    headers.update(kwargs.pop("headers", {}))
    return client.post(
        path,
        content=json.dumps(value).encode(),
        headers=headers,
        **kwargs,
    )


def text_input(value: str, profile: object = None) -> dict[str, object]:
    envelope: dict[str, object] = {"input": {"kind": "text", "value": value}}
    if profile is not None:
        envelope["profile"] = profile
    return envelope


def byte_input(value: bytes, base64_value: str | None = None) -> dict[str, object]:
    return {
        "input": {
            "kind": "bytes",
            "base64": base64_value
            if base64_value is not None
            else base64.b64encode(value).decode(),
            "declared_charset": "utf-8",
        }
    }


def assert_problem(response, status: int, code: str) -> dict[str, object]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    identifier = response.headers["x-request-id"]
    assert REQUEST_ID_RE.fullmatch(identifier)
    assert response.content.endswith(b"\n")
    body = response.json()
    assert list(body) == ["error"]
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == identifier
    return body


def test_health_shape_method_and_query_contract(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "deployment": "api-v1",
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "unicode_version": UNICODE_VERSION,
    }
    assert response.content.endswith(b"\n")

    method = client.post("/v1/health")
    assert_problem(method, 405, "invalid_request")
    assert method.headers["allow"] == "GET"
    assert_problem(client.get("/v1/health?verbose=1"), 400, "invalid_request")


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        None,
        {"input": []},
        {"input": {"kind": "file", "value": "ok"}},
        {"input": {"kind": "text", "value": "ok", "extra": True}},
        {"input": {"kind": "text", "value": "ok"}, "extra": True},
    ],
)
def test_invalid_request_envelopes(client: TestClient, value: object) -> None:
    assert_problem(post_json(client, value), 400, "invalid_request")


def test_unpaired_surrogate_and_malformed_json_are_invalid_requests(client: TestClient) -> None:
    assert_problem(post_json(client, text_input("\ud800")), 400, "invalid_request")
    response = client.post(
        "/v1/hidden-characters",
        content=b'{"input":}',
        headers={"Content-Type": "application/json", **ACTOR_HEADERS},
    )
    assert_problem(response, 400, "invalid_request")
    assert_problem(
        client.post(
            "/v1/hidden-characters?profile=general",
            content=b"{}",
            headers={"Content-Type": "application/json", **ACTOR_HEADERS},
        ),
        400,
        "invalid_request",
    )


def test_invalid_envelope_utf8(client: TestClient) -> None:
    response = client.post(
        "/v1/hidden-characters",
        content=b'{"x":"\xff"}',
        headers={"Content-Type": "application/json", **ACTOR_HEADERS},
    )
    assert_problem(response, 400, "invalid_envelope_utf8")


def test_utf8_bom_on_json_envelope_matches_text_decoder_behavior(client: TestClient) -> None:
    source = json.dumps(text_input("ok")).encode()
    response = client.post(
        "/v1/hidden-characters",
        content=b"\xef\xbb\xbf" + source,
        headers={"Content-Type": "application/json", **ACTOR_HEADERS},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("value", ["YQ", "YQ===", "Y Q==", "YQ==\n", "-_8=", "AB==", "===="])
def test_invalid_and_noncanonical_base64(client: TestClient, value: str) -> None:
    assert_problem(post_json(client, byte_input(b"", value)), 400, "invalid_base64")


def test_input_and_envelope_limits(client: TestClient) -> None:
    assert_problem(post_json(client, text_input("a" * (32 * 1024 + 1))), 413, "input_too_large")
    assert_problem(post_json(client, byte_input(b"a" * (32 * 1024 + 1))), 413, "input_too_large")

    declared = client.post(
        "/v1/hidden-characters",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(256 * 1024 + 1),
            **ACTOR_HEADERS,
        },
    )
    assert_problem(declared, 413, "input_too_large")

    actual = client.post(
        "/v1/hidden-characters",
        content=json.dumps({"padding": "a" * (256 * 1024)}).encode(),
        headers={"Content-Type": "application/json", **ACTOR_HEADERS},
    )
    assert_problem(actual, 413, "input_too_large")

    malformed_length = client.post(
        "/v1/hidden-characters",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "01", **ACTOR_HEADERS},
    )
    assert_problem(malformed_length, 400, "invalid_request")


def test_unsupported_profile_media_type_and_encoding(client: TestClient) -> None:
    assert_problem(post_json(client, text_input("ok", "strict")), 400, "unsupported_profile")
    assert_problem(
        client.post(
            "/v1/hidden-characters",
            content=b"{}",
            headers={"Content-Type": "text/plain", **ACTOR_HEADERS},
        ),
        415,
        "unsupported_media_type",
    )
    assert_problem(
        client.post(
            "/v1/hidden-characters",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "identity",
                **ACTOR_HEADERS,
            },
        ),
        415,
        "unsupported_content_encoding",
    )


def test_text_analysis_offsets_and_public_finding(client: TestClient) -> None:
    response = post_json(client, text_input("A😀\nB\u200b"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "issues_found"
    assert body["input"] == {
        "kind": "text",
        "bytes": 10,
        "utf16_code_units": 6,
        "unicode_scalars": 5,
        "lines": 2,
        "offset_basis": "utf8-encoding-of-input-string",
    }
    finding = body["findings"][0]
    assert finding["location"] == {
        "byte_start": 7,
        "byte_end": 10,
        "utf16_start": 5,
        "utf16_end": 6,
        "scalar_start": 4,
        "scalar_end": 5,
        "line": 2,
        "column": 2,
    }
    assert finding["observed"] == {
        "escaped": r"\u200B",
        "code_points": ["U+200B"],
        "utf8_hex": "E2 80 8B",
    }
    assert "label" not in finding
    assert "character" not in finding


def test_valid_and_invalid_byte_analysis(client: TestClient) -> None:
    valid = post_json(client, byte_input("é\u200b".encode()))
    assert valid.status_code == 200
    assert valid.json()["input"]["offset_basis"] == "submitted-bytes"
    assert valid.json()["findings"][0]["location"]["byte_start"] == 2

    invalid = post_json(client, byte_input(bytes([0x61, 0xE2, 0x82])))
    assert invalid.status_code == 200
    assert invalid.json() == {
        "request_id": invalid.headers["x-request-id"],
        "status": "invalid_utf8",
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "unicode_version": UNICODE_VERSION,
        "input": {"kind": "bytes", "bytes": 3, "offset_basis": "submitted-bytes"},
        "encoding": {
            "valid_utf8": False,
            "basis": "submitted-bytes",
            "first_invalid_byte": 1,
        },
        "summary": {"total": 0, "returned": 0, "truncated": False},
        "findings": [],
        "skipped": [{"check": "hidden-characters", "reason": "invalid_utf8"}],
    }


def test_identifier_profile_severity_override(client: TestClient) -> None:
    general = post_json(client, text_input("\u00a0", "general")).json()
    identifier = post_json(client, text_input("\u00a0", "identifier")).json()
    assert general["findings"][0]["severity"] == "information"
    assert identifier["findings"][0]["severity"] == "warning"


def test_mojibake_endpoint_flags_a_likely_legacy_decode(client: TestClient) -> None:
    response = post_json(client, text_input("cafÃ©"), path="/v1/mojibake")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "issues_found"
    assert body["summary"] == {"total": 1, "returned": 1, "truncated": False}
    finding = body["findings"][0]
    assert finding["rule"] == "mojibake.utf8_bytes_as_legacy_text"
    assert finding["location"]["byte_start"] == 3
    assert finding["possible_intended_character"]["code_point"] == "U+00E9"


def test_normalization_endpoint_compares_all_four_forms(client: TestClient) -> None:
    response = post_json(client, text_input("e\u0301"), path="/v1/normalization")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "changes_found"
    assert {name: value["is_normalized"] for name, value in body["forms"].items()} == {
        "NFC": False,
        "NFD": True,
        "NFKC": False,
        "NFKD": True,
    }
    assert [finding["form"] for finding in body["findings"]] == ["NFC", "NFKC"]


def test_mixed_script_endpoint_surfaces_a_curated_confusable(client: TestClient) -> None:
    response = post_json(
        client,
        text_input("pаypal"),
        path="/v1/mixed-script-confusables",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "issues_found"
    assert body["is_mixed_script"] is True
    assert body["dominant_script"] == "Latin"
    assert body["review_recommended"] is True
    assert body["confusable_data"]["uts39_complete"] is False
    assert body["findings"][0]["rule"] == "confusable.curated_ascii_lookalike"


def test_text_counts_endpoint_reports_all_requested_units(client: TestClient) -> None:
    response = post_json(
        client,
        text_input("Cafe\u0301 👩🏽\u200d💻\r\nflag"),
        path="/v1/text-counts",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["counts"] == {
        "utf8_bytes": 28,
        "unicode_code_points": 16,
        "unicode_scalars": 16,
        "grapheme_clusters": 11,
        "words": 2,
        "lines": 2,
        "javascript_string_units": 19,
    }
    assert body["input"]["kind"] == "text"
    assert body["encoding"]["valid_utf8"] is True


def test_json_validation_endpoint_treats_inner_syntax_as_a_result(
    client: TestClient,
) -> None:
    valid = post_json(
        client,
        text_input('{"name":"Ada"}'),
        path="/v1/json-validation",
    )
    assert valid.status_code == 200
    assert valid.json()["status"] == "valid_json"
    assert valid.json()["valid"] is True
    assert valid.json()["value_type"] == "object"

    invalid = post_json(
        client,
        text_input('{"name": }'),
        path="/v1/json-validation",
    )
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "invalid_json"
    assert invalid.json()["valid"] is False
    assert invalid.json()["error"]["code"] == "expected_value"


def test_code_points_endpoint_returns_every_accepted_character(
    client: TestClient,
) -> None:
    response = post_json(client, text_input("A😀"), path="/v1/code-points")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["summary"] == {"total": 2, "returned": 2, "truncated": False}
    assert [item["code_point"] for item in body["characters"]] == ["U+0041", "U+1F600"]
    assert body["characters"][1]["position"]["byte_start"] == 1

    too_many = post_json(
        client,
        text_input("A" * (DETAIL_LIMIT + 1)),
        path="/v1/code-points",
    )
    assert_problem(too_many, 413, "input_too_large")


def test_cors_preflight_and_regular_cors(client: TestClient) -> None:
    allowed_origin = "https://utf8.ai"
    success = client.options(
        "/v1/hidden-characters",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert success.status_code == 204
    assert success.content == b""
    assert success.headers["access-control-allow-origin"] == allowed_origin
    assert success.headers["access-control-allow-methods"] == "POST, OPTIONS"
    assert success.headers["access-control-allow-headers"] == "Content-Type"
    assert success.headers["access-control-max-age"] == "600"

    for headers in [
        {"Origin": "https://example.test", "Access-Control-Request-Method": "POST"},
        {"Origin": allowed_origin, "Access-Control-Request-Method": "PUT"},
        {
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    ]:
        response = client.options("/v1/hidden-characters", headers=headers)
        assert_problem(response, 400, "invalid_request")

    regular = post_json(client, text_input("ok"), headers={"Origin": allowed_origin})
    assert regular.headers["access-control-allow-origin"] == allowed_origin
    assert regular.headers["access-control-expose-headers"] == "X-Request-ID"


@pytest.mark.parametrize("path", TOOL_PATHS)
def test_tool_routes_share_strict_http_and_input_contract(
    client: TestClient, path: str
) -> None:
    method = client.get(path)
    assert_problem(method, 405, "invalid_request")
    assert method.headers["allow"] == "POST, OPTIONS"

    assert_problem(
        post_json(client, text_input("ok"), path=f"{path}?unexpected=1"),
        400,
        "invalid_request",
    )
    assert_problem(
        post_json(client, text_input("ok", "general"), path=path),
        400,
        "invalid_request",
    )

    preflight = client.options(
        path,
        headers={
            "Origin": "https://utf8.ai",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert preflight.status_code == 204


@pytest.mark.parametrize(
    ("path", "check"),
    [
        ("/v1/mojibake", "mojibake"),
        ("/v1/normalization", "normalization"),
        ("/v1/mixed-script-confusables", "mixed-script-confusables"),
        ("/v1/text-counts", "text-counts"),
        ("/v1/json-validation", "json-validation"),
        ("/v1/code-points", "code-points"),
    ],
)
def test_tool_routes_report_invalid_original_utf8(
    client: TestClient, path: str, check: str
) -> None:
    response = post_json(client, byte_input(b"\xff"), path=path)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "invalid_utf8"
    assert body["encoding"]["first_invalid_byte"] == 0
    assert body["skipped"] == [{"check": check, "reason": "invalid_utf8"}]


def test_unknown_route_and_document_routes(client: TestClient) -> None:
    assert_problem(client.get("/not-a-route"), 404, "invalid_request")
    redirect = client.get("/docs", follow_redirects=False)
    assert redirect.status_code == 308
    assert redirect.headers["location"] == "/"
    swagger_response = client.get("/")
    assert swagger_response.status_code == 200
    assert "utf8.ai" not in swagger_response.text.lower()
    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    openapi_document = openapi_response.json()
    assert "utf8.ai" not in json.dumps(openapi_document).lower()
    assert openapi_document["servers"] == [
        {"url": "/", "description": "Host serving this documentation"}
    ]


def _resolve_schema(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    assert reference.startswith("#/components/schemas/")
    name = reference.rsplit("/", 1)[-1]
    return document["components"]["schemas"][name]


def _assert_example_matches_schema(
    document: dict[str, Any],
    schema: dict[str, Any],
    value: Any,
    path: str = "$",
) -> None:
    schema = _resolve_schema(document, schema)
    if "oneOf" in schema:
        matches = 0
        failures: list[str] = []
        for candidate in schema["oneOf"]:
            try:
                _assert_example_matches_schema(document, candidate, value, path)
            except AssertionError as error:
                failures.append(str(error))
            else:
                matches += 1
        assert matches == 1, f"{path}: expected exactly one oneOf match; {failures}"
        return

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if value is None and "null" in expected_type:
            return
        expected_type = next(item for item in expected_type if item != "null")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected_type is not None:
        assert type_checks[expected_type](value), (
            f"{path}: expected {expected_type}, got {type(value).__name__}"
        )
    if "const" in schema:
        assert value == schema["const"], f"{path}: expected constant {schema['const']!r}"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} is not in the enum"

    if expected_type == "string" and "pattern" in schema:
        assert re.fullmatch(schema["pattern"], value), f"{path}: pattern mismatch"
    if expected_type == "integer":
        assert value >= schema.get("minimum", value), f"{path}: below minimum"
        assert value <= schema.get("maximum", value), f"{path}: above maximum"
    if expected_type == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        assert not missing, f"{path}: missing required properties {sorted(missing)}"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            assert not extra, f"{path}: extra properties {sorted(extra)}"
        for name, item in value.items():
            if name in properties:
                _assert_example_matches_schema(
                    document, properties[name], item, f"{path}.{name}"
                )
    if expected_type == "array":
        assert len(value) <= schema.get("maxItems", len(value)), f"{path}: too many items"
        prefix_items = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix_items):
            _assert_example_matches_schema(document, item_schema, value[index], f"{path}[{index}]")
        item_schema = schema.get("items")
        if item_schema is False:
            assert len(value) == len(prefix_items), f"{path}: unexpected trailing items"
        elif isinstance(item_schema, dict):
            for index, item in enumerate(value[len(prefix_items) :], len(prefix_items)):
                _assert_example_matches_schema(
                    document, item_schema, item, f"{path}[{index}]"
                )


def test_static_openapi_is_current_complete_and_structurally_valid() -> None:
    with open(main_module.STATIC_DIR / "openapi.json", encoding="utf-8") as source:
        document = json.load(source)

    assert document == build_document()
    OpenAPI.model_validate(document)
    expected_paths = {
        "/v1/health",
        "/v1/hidden-characters",
        *IMPLEMENTED_TOOL_PATHS,
    }
    assert set(document["paths"]) == expected_paths

    operation_ids = [
        operation["operationId"]
        for path_item in document["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post"}
    ]
    assert len(operation_ids) == len(set(operation_ids)) == len(expected_paths)

    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post"}:
                continue
            if "requestBody" in operation:
                media = operation["requestBody"]["content"]["application/json"]
                for example in media.get("examples", {}).values():
                    _assert_example_matches_schema(document, media["schema"], example["value"])
            for response in operation["responses"].values():
                if "$ref" in response or "content" not in response:
                    continue
                media = response["content"]["application/json"]
                if "example" in media:
                    _assert_example_matches_schema(document, media["schema"], media["example"])
                for example in media.get("examples", {}).values():
                    _assert_example_matches_schema(document, media["schema"], example["value"])

    for response in document["components"]["responses"].values():
        media = response["content"]["application/json"]
        _assert_example_matches_schema(document, media["schema"], media["example"])


def test_openapi_success_examples_match_live_endpoints(client: TestClient) -> None:
    document = build_document()
    response_example_names = {
        "/v1/hidden-characters": "findings",
        **{path: "completed" for path in IMPLEMENTED_TOOL_PATHS},
    }
    for path, example_name in response_example_names.items():
        operation = document["paths"][path]["post"]
        request_example = operation["requestBody"]["content"]["application/json"][
            "examples"
        ]["text"]["value"]
        response = post_json(client, request_example, path=path)
        assert response.status_code == 200
        actual = response.json()
        expected = operation["responses"]["200"]["content"]["application/json"][
            "examples"
        ][example_name]["value"]
        expected = {
            **expected,
            "request_id": actual["request_id"],
            "unicode_version": actual["unicode_version"],
        }
        assert actual == expected


def test_rate_limited_after_configured_maximum(client: TestClient) -> None:
    for _ in range(rate_limit.RATE_LIMIT_MAX_REQUESTS):
        assert post_json(client, text_input("ok")).status_code == 200
    limited = post_json(client, text_input("ok"))
    assert_problem(limited, 429, "rate_limited")
    assert limited.headers["retry-after"] == "60"


def test_limiter_unavailable_without_secret_off_localhost(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("API_RATE_LIMIT_HMAC_KEY")
    monkeypatch.delenv("LOCAL_DEVELOPMENT", raising=False)
    assert_problem(post_json(client, text_input("ok")), 503, "limiter_unavailable")


def test_internal_error_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*_: object) -> dict[str, object]:
        raise RuntimeError("private-marker")

    monkeypatch.setattr(main_module, "analyze_request", fail)
    with TestClient(
        app,
        base_url="https://api.utf8.ai",
        raise_server_exceptions=False,
    ) as test_client:
        response = post_json(test_client, text_input("private-marker"))
    assert_problem(response, 500, "internal_error")
    assert "private-marker" not in response.text
