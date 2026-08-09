"""Generate the reviewed static OpenAPI contract using only the standard library."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.engine import (
    DETAIL_LIMIT,
    ENGINE_VERSION,
    RULESET_VERSION,
    analyze_hidden,
)
from app.text_tools import count_text, inspect_code_points, validate_json
from app.unicode_review import check_normalization, detect_mojibake, review_mixed_scripts

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "openapi.json"
EXAMPLE_REQUEST_ID = "req_0123456789abcdef0123456789abcdef"
EXAMPLE_UNICODE_VERSION = "runtime-dependent"


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def exact_object(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": required if required is not None else list(properties),
        "properties": properties,
    }
    if description is not None:
        schema["description"] = description
    return schema


def string_enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def nonnegative_integer(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "minimum": 0}
    if description is not None:
        schema["description"] = description
    return schema


def array_of(item: dict[str, Any], *, max_items: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": item}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def tool_base_example(text: str, status: str) -> dict[str, Any]:
    counts = count_text(text)
    return {
        "request_id": EXAMPLE_REQUEST_ID,
        "status": status,
        "engine_version": ENGINE_VERSION,
        "unicode_version": EXAMPLE_UNICODE_VERSION,
        "input": {
            "kind": "text",
            "bytes": counts["utf8_bytes"],
            "utf16_code_units": counts["javascript_string_units"],
            "unicode_scalars": counts["unicode_scalars"],
            "lines": counts["lines"],
            "offset_basis": "utf8-encoding-of-input-string",
        },
        "encoding": {
            "valid_utf8": True,
            "basis": "strict-request-envelope-and-reencoded-text",
        },
    }


def invalid_utf8_tool_example(check: str) -> dict[str, Any]:
    return {
        "request_id": EXAMPLE_REQUEST_ID,
        "status": "invalid_utf8",
        "engine_version": ENGINE_VERSION,
        "unicode_version": EXAMPLE_UNICODE_VERSION,
        "input": {"kind": "bytes", "bytes": 1, "offset_basis": "submitted-bytes"},
        "encoding": {
            "valid_utf8": False,
            "basis": "submitted-bytes",
            "first_invalid_byte": 0,
        },
        "skipped": [{"check": check, "reason": "invalid_utf8"}],
    }


def hidden_example() -> dict[str, Any]:
    text = "pay\u200bload"
    analysis = analyze_hidden(text, "general")
    return {
        "request_id": EXAMPLE_REQUEST_ID,
        "status": "issues_found",
        "engine_version": ENGINE_VERSION,
        "ruleset_version": RULESET_VERSION,
        "unicode_version": EXAMPLE_UNICODE_VERSION,
        "profile": "general",
        "input": {
            "kind": "text",
            **analysis["metrics"],
            "offset_basis": "utf8-encoding-of-input-string",
        },
        "encoding": {
            "valid_utf8": True,
            "basis": "strict-request-envelope-and-reencoded-text",
        },
        "summary": {
            "total": analysis["total"],
            "returned": len(analysis["findings"]),
            "truncated": analysis["total"] > DETAIL_LIMIT,
        },
        "findings": [
            {
                key: finding[key]
                for key in (
                    "id",
                    "rule",
                    "category",
                    "severity",
                    "title",
                    "location",
                    "observed",
                    "explanation",
                )
            }
            for finding in analysis["findings"]
        ],
    }


def hidden_invalid_utf8_example() -> dict[str, Any]:
    example = invalid_utf8_tool_example("hidden-characters")
    example["ruleset_version"] = RULESET_VERSION
    example["summary"] = {"total": 0, "returned": 0, "truncated": False}
    example["findings"] = []
    return example


def mojibake_example() -> dict[str, Any]:
    text = "cafÃ©"
    analysis = detect_mojibake(text)
    return {
        **tool_base_example(text, "issues_found"),
        "check": analysis["check"],
        "summary": analysis["summary"],
        "findings": analysis["findings"],
    }


def normalization_example() -> dict[str, Any]:
    text = "Cafe\u0301"
    analysis = check_normalization(text)
    return {
        **tool_base_example(text, "changes_found"),
        "check": analysis["check"],
        "forms": analysis["forms"],
        "summary": analysis["summary"],
        "findings": analysis["findings"],
    }


def mixed_script_example() -> dict[str, Any]:
    text = "pаypal"
    analysis = review_mixed_scripts(text)
    return {
        **tool_base_example(text, "issues_found"),
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


def text_counts_example() -> dict[str, Any]:
    text = "café\n😀"
    return {**tool_base_example(text, "complete"), "counts": count_text(text)}


def json_validation_example() -> dict[str, Any]:
    text = '{"name": }'
    validation = validate_json(text)
    return {
        **tool_base_example(text, "invalid_json"),
        **validation,
    }


def code_points_example() -> dict[str, Any]:
    text = "A😀"
    return {
        **tool_base_example(text, "complete"),
        **inspect_code_points(text),
    }


def common_properties(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": ref("RequestId"),
        "status": status,
        "engine_version": {"type": "string"},
        "unicode_version": {"type": "string"},
        "input": ref("InputMetrics"),
        "encoding": ref("ValidEncoding"),
    }


def tool_result_schema(
    status: dict[str, Any], extra_properties: dict[str, Any]
) -> dict[str, Any]:
    properties = {**common_properties(status), **extra_properties}
    return exact_object(properties)


def request_body(text: str, summary: str) -> dict[str, Any]:
    return {
        "required": True,
        "description": (
            "Strict JSON envelope. Tool endpoints reject profile and every unknown property."
        ),
        "content": {
            "application/json": {
                "schema": ref("ToolRequest"),
                "examples": {
                    "text": {
                        "summary": summary,
                        "value": {"input": {"kind": "text", "value": text}},
                    },
                    "bytes": {
                        "summary": "Submit original UTF-8 bytes as canonical Base64",
                        "value": {
                            "input": {
                                "kind": "bytes",
                                "base64": "Y2Fmw6k=",
                                "declared_charset": "utf-8",
                            }
                        },
                    },
                },
            }
        },
    }


def standard_post_responses(
    success_schema: str,
    success_description: str,
    success_example: dict[str, Any],
    check: str,
) -> dict[str, Any]:
    return {
        "200": {
            "description": success_description,
            "headers": {"X-Request-ID": {"$ref": "#/components/headers/RequestId"}},
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [ref(success_schema), ref("ToolInvalidUtf8Response")]
                    },
                    "examples": {
                        "completed": {"value": success_example},
                        "invalidUtf8": {"value": invalid_utf8_tool_example(check)},
                    },
                }
            },
        },
        "400": {"$ref": "#/components/responses/AnalysisBadRequest"},
        "405": {"$ref": "#/components/responses/MethodNotAllowedPost"},
        "413": {"$ref": "#/components/responses/InputTooLarge"},
        "415": {"$ref": "#/components/responses/UnsupportedRequestEncoding"},
        "429": {"$ref": "#/components/responses/RateLimited"},
        "500": {"$ref": "#/components/responses/InternalError"},
        "503": {"$ref": "#/components/responses/LimiterUnavailable"},
    }


def post_operation(
    *,
    tag: str,
    summary: str,
    description: str,
    operation_id: str,
    request_text: str,
    request_summary: str,
    success_schema: str,
    success_description: str,
    success_example: dict[str, Any],
    check: str,
) -> dict[str, Any]:
    return {
        "post": {
            "tags": [tag],
            "summary": summary,
            "description": description,
            "operationId": operation_id,
            "requestBody": request_body(request_text, request_summary),
            "responses": standard_post_responses(
                success_schema, success_description, success_example, check
            ),
        }
    }


def error_response(code: str, status: int, description: str) -> dict[str, Any]:
    return {
        "description": description,
        "headers": {"X-Request-ID": {"$ref": "#/components/headers/RequestId"}},
        "content": {
            "application/json": {
                "schema": ref("ErrorResponse"),
                "example": {
                    "error": {
                        "code": code,
                        "message": {
                            400: "The request body does not match the API contract.",
                            405: "The request body does not match the API contract.",
                            413: "The request or decoded input exceeds its size limit.",
                            415: "Content-Type must be application/json.",
                            429: "The anonymous API rate limit has been reached.",
                            500: "The API could not complete the request.",
                            503: "The anonymous API limiter is unavailable.",
                        }[status],
                        "request_id": EXAMPLE_REQUEST_ID,
                    }
                },
            }
        },
    }


def build_schemas() -> dict[str, Any]:
    source_location_properties = {
        "byte_start": nonnegative_integer(),
        "byte_end": nonnegative_integer(),
        "utf16_start": nonnegative_integer(),
        "utf16_end": nonnegative_integer(),
        "scalar_start": nonnegative_integer(),
        "scalar_end": nonnegative_integer(),
        "line": {"type": "integer", "minimum": 1},
        "column": {"type": "integer", "minimum": 1},
        "line_end": {"type": "integer", "minimum": 1},
        "column_end": {"type": "integer", "minimum": 1},
    }
    common_character_properties = {
        "escaped": {"type": "string"},
        "code_point": {"type": "string", "pattern": "^U\\+[0-9A-F]{4,6}$"},
        "utf8_hex": {"type": "string"},
        "name": {"type": "string"},
        "category": {"type": "string", "pattern": "^[A-Z][a-z]$"},
        "script": {"type": "string"},
        "location": ref("SourceLocation"),
    }
    summary = exact_object(
        {
            "total": nonnegative_integer(),
            "returned": nonnegative_integer(),
            "truncated": {"type": "boolean"},
        }
    )
    tool_invalid_properties = {
        "request_id": ref("RequestId"),
        "status": {"type": "string", "const": "invalid_utf8"},
        "engine_version": {"type": "string"},
        "unicode_version": {"type": "string"},
        "input": ref("InvalidUtf8InputMetrics"),
        "encoding": ref("InvalidEncoding"),
        "skipped": array_of(ref("SkippedCheck"), max_items=1),
    }

    hidden_success_properties = {
        "request_id": ref("RequestId"),
        "status": string_enum("clean", "issues_found"),
        "engine_version": {"type": "string"},
        "ruleset_version": {"type": "string"},
        "unicode_version": {"type": "string"},
        "profile": ref("Profile"),
        "input": ref("InputMetrics"),
        "encoding": ref("ValidEncoding"),
        "summary": ref("Summary"),
        "findings": array_of(ref("HiddenFinding"), max_items=DETAIL_LIMIT),
    }
    hidden_invalid_properties = {
        **tool_invalid_properties,
        "ruleset_version": {"type": "string"},
        "summary": ref("Summary"),
        "findings": array_of(ref("HiddenFinding"), max_items=0),
    }

    return {
        "RequestId": {
            "type": "string",
            "pattern": "^req_[0-9a-f]{32}$",
            "example": EXAMPLE_REQUEST_ID,
        },
        "HealthResponse": exact_object(
            {
                "status": {"type": "string", "const": "ok"},
                "deployment": {"type": "string", "const": "api-v1"},
                "engine_version": {"type": "string"},
                "ruleset_version": {"type": "string"},
                "unicode_version": {
                    "type": "string",
                    "description": "Unicode database version supplied by the Python runtime.",
                },
            }
        ),
        "Profile": {
            "type": "string",
            "enum": ["general", "identifier"],
            "default": "general",
        },
        "TextInput": exact_object(
            {
                "kind": {"type": "string", "const": "text"},
                "value": {
                    "type": "string",
                    "description": (
                        "Unicode scalar text whose UTF-8 encoding is at most 32 KiB."
                    ),
                },
            }
        ),
        "ByteInput": exact_object(
            {
                "kind": {"type": "string", "const": "bytes"},
                "base64": {
                    "type": "string",
                    "contentEncoding": "base64",
                    "description": (
                        "Canonical padded standard Base64 with no whitespace; decoded input "
                        "is at most 32 KiB."
                    ),
                },
                "declared_charset": {"type": "string", "const": "utf-8"},
            }
        ),
        "AnalysisRequest": exact_object(
            {
                "input": {
                    "oneOf": [ref("TextInput"), ref("ByteInput")],
                    "discriminator": {
                        "propertyName": "kind",
                        "mapping": {
                            "text": "#/components/schemas/TextInput",
                            "bytes": "#/components/schemas/ByteInput",
                        },
                    },
                },
                "profile": ref("Profile"),
            },
            required=["input"],
        ),
        "ToolRequest": exact_object(
            {
                "input": {
                    "oneOf": [ref("TextInput"), ref("ByteInput")],
                    "discriminator": {
                        "propertyName": "kind",
                        "mapping": {
                            "text": "#/components/schemas/TextInput",
                            "bytes": "#/components/schemas/ByteInput",
                        },
                    },
                }
            }
        ),
        "InputMetrics": exact_object(
            {
                "kind": string_enum("text", "bytes"),
                "bytes": nonnegative_integer(),
                "utf16_code_units": nonnegative_integer(),
                "unicode_scalars": nonnegative_integer(),
                "lines": {"type": "integer", "minimum": 1},
                "offset_basis": string_enum(
                    "submitted-bytes", "utf8-encoding-of-input-string"
                ),
            }
        ),
        "InvalidUtf8InputMetrics": exact_object(
            {
                "kind": {"type": "string", "const": "bytes"},
                "bytes": nonnegative_integer(),
                "offset_basis": {"type": "string", "const": "submitted-bytes"},
            }
        ),
        "ValidEncoding": exact_object(
            {
                "valid_utf8": {"type": "boolean", "const": True},
                "basis": string_enum(
                    "submitted-bytes", "strict-request-envelope-and-reencoded-text"
                ),
            }
        ),
        "InvalidEncoding": exact_object(
            {
                "valid_utf8": {"type": "boolean", "const": False},
                "basis": {"type": "string", "const": "submitted-bytes"},
                "first_invalid_byte": nonnegative_integer(),
            }
        ),
        "SkippedCheck": exact_object(
            {
                "check": string_enum(
                    "hidden-characters",
                    "mojibake",
                    "normalization",
                    "mixed-script-confusables",
                    "text-counts",
                    "json-validation",
                    "code-points",
                ),
                "reason": {"type": "string", "const": "invalid_utf8"},
            }
        ),
        "Summary": summary,
        "SourceLocation": exact_object(
            source_location_properties,
            required=[
                "byte_start",
                "byte_end",
                "utf16_start",
                "utf16_end",
                "scalar_start",
                "scalar_end",
                "line",
                "column",
            ],
            description=(
                "Zero-based half-open byte, UTF-16, and scalar offsets with one-based "
                "line and column coordinates. End coordinates are present on Unicode-review "
                "findings."
            ),
        ),
        "ObservedCodePoints": exact_object(
            {
                "escaped": {"type": "string"},
                "code_points": array_of(
                    {"type": "string", "pattern": "^U\\+[0-9A-F]{4,6}$"}
                ),
                "utf8_hex": {"type": "string"},
            }
        ),
        "HiddenFinding": exact_object(
            {
                "id": {"type": "string"},
                "rule": {"type": "string"},
                "category": string_enum(
                    "hidden_text",
                    "formatting",
                    "bidirectional",
                    "control",
                    "whitespace",
                ),
                "severity": string_enum("information", "warning", "error"),
                "title": {"type": "string"},
                "location": ref("SourceLocation"),
                "observed": ref("ObservedCodePoints"),
                "explanation": {"type": "string"},
            }
        ),
        "HiddenAnalysisSuccess": exact_object(hidden_success_properties),
        "HiddenInvalidUtf8Response": exact_object(hidden_invalid_properties),
        "HiddenAnalysisResponse": {
            "oneOf": [ref("HiddenAnalysisSuccess"), ref("HiddenInvalidUtf8Response")]
        },
        "ToolInvalidUtf8Response": exact_object(tool_invalid_properties),
        "CharacterDetail": exact_object(
            common_character_properties,
            required=["escaped", "code_point", "utf8_hex", "name", "category", "script"],
        ),
        "BoundedCharacterDetails": exact_object(
            {
                "characters": array_of(ref("CharacterDetail"), max_items=DETAIL_LIMIT),
                "total": nonnegative_integer(),
                "returned": nonnegative_integer(),
                "truncated": {"type": "boolean"},
            }
        ),
        "MojibakeObserved": exact_object(
            {
                "characters": array_of(ref("CharacterDetail"), max_items=4),
                "interpreted_bytes_hex": {"type": "string"},
            },
            required=["characters"],
        ),
        "MojibakeFinding": exact_object(
            {
                "id": {"type": "string"},
                "rule": string_enum(
                    "mojibake.replacement_character",
                    "mojibake.utf8_bytes_as_legacy_text",
                ),
                "category": {"type": "string", "const": "mojibake"},
                "severity": {"type": "string", "const": "warning"},
                "title": {"type": "string"},
                "location": ref("SourceLocation"),
                "observed": ref("MojibakeObserved"),
                "possible_intended_character": ref("CharacterDetail"),
                "explanation": {"type": "string"},
            },
            required=[
                "id",
                "rule",
                "category",
                "severity",
                "title",
                "location",
                "observed",
                "explanation",
            ],
        ),
        "MojibakeResponse": tool_result_schema(
            string_enum("clean", "issues_found"),
            {
                "check": {"type": "string", "const": "mojibake"},
                "summary": ref("Summary"),
                "findings": array_of(ref("MojibakeFinding"), max_items=DETAIL_LIMIT),
            },
        ),
        "NormalizationMetrics": exact_object(
            {
                "bytes": nonnegative_integer(),
                "unicode_scalars": nonnegative_integer(),
                "utf16_code_units": nonnegative_integer(),
                "lines": {"type": "integer", "minimum": 1},
            }
        ),
        "NormalizationForm": exact_object(
            {
                "is_normalized": {"type": "boolean"},
                "metrics": ref("NormalizationMetrics"),
            }
        ),
        "NormalizationForms": exact_object(
            {form: ref("NormalizationForm") for form in ("NFC", "NFD", "NFKC", "NFKD")}
        ),
        "NormalizationFinding": exact_object(
            {
                "id": {"type": "string"},
                "rule": {"type": "string"},
                "category": {"type": "string", "const": "normalization"},
                "severity": {"type": "string", "const": "information"},
                "title": {"type": "string"},
                "form": string_enum("NFC", "NFD", "NFKC", "NFKD"),
                "location": ref("SourceLocation"),
                "observed": ref("BoundedCharacterDetails"),
                "normalized": ref("BoundedCharacterDetails"),
                "explanation": {"type": "string"},
            }
        ),
        "NormalizationResponse": tool_result_schema(
            string_enum("normalized", "changes_found"),
            {
                "check": {"type": "string", "const": "normalization"},
                "forms": ref("NormalizationForms"),
                "summary": ref("Summary"),
                "findings": array_of(ref("NormalizationFinding"), max_items=4),
            },
        ),
        "ConfusableData": exact_object(
            {
                "kind": {"type": "string", "const": "curated_subset"},
                "version": {"type": "string"},
                "source_scripts": {
                    "type": "array",
                    "prefixItems": [
                        {"type": "string", "const": "Cyrillic"},
                        {"type": "string", "const": "Greek"},
                    ],
                    "items": False,
                },
                "target_script": {"type": "string", "const": "ASCII Latin"},
                "uts39_complete": {"type": "boolean", "const": False},
            }
        ),
        "ScriptSummary": exact_object(
            {
                "script": {"type": "string"},
                "count": {"type": "integer", "minimum": 1},
                "first_scalar": nonnegative_integer(),
            }
        ),
        "MixedScriptFinding": exact_object(
            {
                "id": {"type": "string"},
                "rule": string_enum(
                    "mixed_script.character", "confusable.curated_ascii_lookalike"
                ),
                "category": string_enum("mixed_script", "confusable"),
                "severity": {"type": "string", "const": "warning"},
                "title": {"type": "string"},
                "location": ref("SourceLocation"),
                "observed": ref("CharacterDetail"),
                "looks_like": ref("CharacterDetail"),
                "confusable_data_version": {"type": "string"},
                "explanation": {"type": "string"},
            },
            required=[
                "id",
                "rule",
                "category",
                "severity",
                "title",
                "location",
                "observed",
                "explanation",
            ],
        ),
        "MixedScriptResponse": tool_result_schema(
            string_enum("clean", "issues_found"),
            {
                "check": {
                    "type": "string",
                    "const": "mixed_scripts_and_confusables",
                },
                "confusable_data": ref("ConfusableData"),
                "scripts": array_of(ref("ScriptSummary")),
                "dominant_script": {"type": ["string", "null"]},
                "is_mixed_script": {"type": "boolean"},
                "expected_script_combination": {"type": "boolean"},
                "review_recommended": {"type": "boolean"},
                "summary": ref("Summary"),
                "findings": array_of(ref("MixedScriptFinding"), max_items=DETAIL_LIMIT),
            },
        ),
        "TextCounts": exact_object(
            {
                "utf8_bytes": nonnegative_integer(),
                "unicode_code_points": nonnegative_integer(),
                "unicode_scalars": nonnegative_integer(),
                "grapheme_clusters": nonnegative_integer(),
                "words": nonnegative_integer(),
                "lines": {"type": "integer", "minimum": 1},
                "javascript_string_units": nonnegative_integer(),
            }
        ),
        "TextCountsResponse": tool_result_schema(
            {"type": "string", "const": "complete"},
            {"counts": ref("TextCounts")},
        ),
        "JsonError": exact_object(
            {
                "code": string_enum(
                    "trailing_comma",
                    "unexpected_end",
                    "comment_not_allowed",
                    "single_quoted_string",
                    "expected_value",
                    "expected_property_name",
                    "expected_colon",
                    "expected_comma_or_end",
                    "extra_data",
                    "unterminated_string",
                    "invalid_unicode_escape",
                    "invalid_escape",
                    "unescaped_control_character",
                    "unexpected_bom",
                    "non_standard_number",
                    "nesting_too_deep",
                    "invalid_syntax",
                ),
                "message": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
                "character_offset": nonnegative_integer(),
                "byte_offset": nonnegative_integer(),
            }
        ),
        "ValidJsonResponse": tool_result_schema(
            {"type": "string", "const": "valid_json"},
            {
                "valid": {"type": "boolean", "const": True},
                "value_type": string_enum(
                    "object", "array", "string", "number", "boolean", "null"
                ),
            },
        ),
        "InvalidJsonResponse": tool_result_schema(
            {"type": "string", "const": "invalid_json"},
            {
                "valid": {"type": "boolean", "const": False},
                "error": ref("JsonError"),
            },
        ),
        "JsonValidationResponse": {
            "oneOf": [ref("ValidJsonResponse"), ref("InvalidJsonResponse")]
        },
        "CodePointPosition": exact_object(
            {
                "byte_start": nonnegative_integer(),
                "byte_end": nonnegative_integer(),
                "code_point_start": nonnegative_integer(),
                "code_point_end": nonnegative_integer(),
                "javascript_unit_start": nonnegative_integer(),
                "javascript_unit_end": nonnegative_integer(),
                "line": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            }
        ),
        "CodePointItem": exact_object(
            {
                "index": nonnegative_integer(),
                "code_point": {"type": "string", "pattern": "^U\\+[0-9A-F]{4,6}$"},
                "decimal": nonnegative_integer(),
                "name": {"type": "string"},
                "category": {"type": "string", "pattern": "^[A-Z][a-z]$"},
                "utf8_bytes": array_of(
                    {"type": "integer", "minimum": 0, "maximum": 255}, max_items=4
                ),
                "utf8_hex": {"type": "string"},
                "position": ref("CodePointPosition"),
                "visible": {
                    "type": "string",
                    "description": (
                        "The character when printable, a dotted-circle form for a mark, or "
                        "an escaped representation for controls, separators, and format characters."
                    ),
                },
            }
        ),
        "CodePointsResponse": tool_result_schema(
            {"type": "string", "const": "complete"},
            {
                "summary": ref("Summary"),
                "characters": array_of(ref("CodePointItem"), max_items=DETAIL_LIMIT),
            },
        ),
        "Error": exact_object(
            {
                "code": string_enum(
                    "invalid_request",
                    "invalid_envelope_utf8",
                    "invalid_base64",
                    "input_too_large",
                    "unsupported_profile",
                    "unsupported_media_type",
                    "unsupported_content_encoding",
                    "rate_limited",
                    "limiter_unavailable",
                    "internal_error",
                ),
                "message": {"type": "string"},
                "request_id": ref("RequestId"),
            }
        ),
        "ErrorResponse": exact_object({"error": ref("Error")}),
    }


def build_document() -> dict[str, Any]:
    hidden_request_body = {
        "required": True,
        "description": "Strict envelope; profile is accepted only by this endpoint.",
        "content": {
            "application/json": {
                "schema": ref("AnalysisRequest"),
                "examples": {
                    "text": {
                        "value": {
                            "input": {"kind": "text", "value": "pay\u200bload"},
                            "profile": "general",
                        }
                    },
                    "bytes": {
                        "value": {
                            "input": {
                                "kind": "bytes",
                                "base64": "cGF5bG9hZA==",
                                "declared_charset": "utf-8",
                            },
                            "profile": "identifier",
                        }
                    },
                },
            }
        },
    }
    hidden_responses = standard_post_responses(
        "HiddenAnalysisSuccess",
        "Hidden-character analysis completed or original bytes were invalid UTF-8.",
        hidden_example(),
        "hidden-characters",
    )
    hidden_responses["200"]["content"]["application/json"] = {
        "schema": ref("HiddenAnalysisResponse"),
        "examples": {
            "findings": {"value": hidden_example()},
            "invalidUtf8": {"value": hidden_invalid_utf8_example()},
        },
    }

    paths = {
        "/v1/health": {
            "get": {
                "tags": ["Service"],
                "summary": "Check API health",
                "description": (
                    "Returns deployed engine, hidden-ruleset, and runtime Unicode versions. "
                    "Query parameters are rejected and this endpoint does not consume quota."
                ),
                "operationId": "getHealth",
                "responses": {
                    "200": {
                        "description": "The API is available.",
                        "headers": {
                            "X-Request-ID": {"$ref": "#/components/headers/RequestId"}
                        },
                        "content": {
                            "application/json": {
                                "schema": ref("HealthResponse"),
                                "example": {
                                    "status": "ok",
                                    "deployment": "api-v1",
                                    "engine_version": ENGINE_VERSION,
                                    "ruleset_version": RULESET_VERSION,
                                    "unicode_version": EXAMPLE_UNICODE_VERSION,
                                },
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/InvalidRequest"},
                    "405": {"$ref": "#/components/responses/MethodNotAllowedGet"},
                },
            }
        },
        "/v1/hidden-characters": {
            "post": {
                "tags": ["Detection"],
                "summary": "Analyze hidden characters",
                "description": (
                    "Reports invisible, formatting, bidirectional, whitespace, and control "
                    "characters with exact offsets. Findings never include a raw character field."
                ),
                "operationId": "analyzeHiddenCharacters",
                "requestBody": hidden_request_body,
                "responses": hidden_responses,
            }
        },
        "/v1/mojibake": post_operation(
            tag="Detection",
            summary="Detect likely mojibake",
            description=(
                "Flags U+FFFD and complete UTF-8 sequences that appear to have been decoded "
                "through Latin-1 or Windows-1252. Results are heuristics, not proof or repair."
            ),
            operation_id="detectMojibake",
            request_text="cafÃ©",
            request_summary="Review a likely UTF-8-as-legacy-decoding artifact",
            success_schema="MojibakeResponse",
            success_description="Mojibake review completed.",
            success_example=mojibake_example(),
            check="mojibake",
        ),
        "/v1/normalization": post_operation(
            tag="Unicode",
            summary="Check Unicode normalization",
            description=(
                "Compares text with NFC, NFD, NFKC, and NFKD. It returns form flags, metrics, "
                "and bounded changed ranges instead of full normalized strings."
            ),
            operation_id="checkUnicodeNormalization",
            request_text="Cafe\u0301",
            request_summary="Compare decomposed text with all four normalization forms",
            success_schema="NormalizationResponse",
            success_description="Normalization comparison completed.",
            success_example=normalization_example(),
            check="normalization",
        ),
        "/v1/mixed-script-confusables": post_operation(
            tag="Unicode",
            summary="Review mixed scripts and confusables",
            description=(
                "Summarizes writing systems and flags suspicious cross-script characters. "
                "Confusable matching is an explicitly versioned Greek/Cyrillic-to-ASCII "
                "curated subset, not complete UTS #39 data."
            ),
            operation_id="reviewMixedScriptConfusables",
            request_text="pаypal",
            request_summary="Review a Cyrillic lookalike in Latin text",
            success_schema="MixedScriptResponse",
            success_description="Mixed-script and confusable review completed.",
            success_example=mixed_script_example(),
            check="mixed-script-confusables",
        ),
        "/v1/text-counts": post_operation(
            tag="Text",
            summary="Count UTF-8 and Unicode text units",
            description=(
                "Counts UTF-8 bytes, code points/scalars, locally segmented extended grapheme "
                "clusters, Unicode-aware words, CR/LF/CRLF lines, and UTF-16 JavaScript units."
            ),
            operation_id="countUtf8Text",
            request_text="café\n😀",
            request_summary="Count text containing non-ASCII and non-BMP characters",
            success_schema="TextCountsResponse",
            success_description="All requested units were counted.",
            success_example=text_counts_example(),
            check="text-counts",
        ),
        "/v1/json-validation": post_operation(
            tag="JSON",
            summary="Validate JSON text",
            description=(
                "Validates the submitted inner text as JSON, accepts every standard top-level "
                "type, rejects NaN and infinities, and returns stable source locations. Invalid "
                "inner JSON is a successful HTTP 200 domain result."
            ),
            operation_id="validateJson",
            request_text='{"name": }',
            request_summary="Locate a syntax error in submitted JSON text",
            success_schema="JsonValidationResponse",
            success_description="JSON validation completed.",
            success_example=json_validation_example(),
            check="json-validation",
        ),
        "/v1/code-points": post_operation(
            tag="Unicode",
            summary="Inspect Unicode code points",
            description=(
                f"Lists every code point with UTF-8 bytes, Unicode metadata, offsets, and a "
                f"visible or escaped representation. This endpoint accepts at most "
                f"{DETAIL_LIMIT} code points so its response is complete and bounded."
            ),
            operation_id="inspectUnicodeCodePoints",
            request_text="A😀",
            request_summary="Inspect a BMP letter and a non-BMP emoji",
            success_schema="CodePointsResponse",
            success_description="Every accepted code point was inspected.",
            success_example=code_points_example(),
            check="code-points",
        ),
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "UTF-8 and Unicode Analysis API",
            "version": "1.1.0",
            "license": {"name": "Apache License 2.0", "identifier": "Apache-2.0"},
            "summary": "Validate and inspect UTF-8, Unicode text, and JSON.",
            "description": (
                "Strict, bounded analysis for hidden characters, mojibake, normalization, "
                "mixed scripts and confusables, text counts, JSON syntax, and Unicode code "
                "points. Requests are not persisted or forwarded by application code."
            ),
        },
        "servers": [{"url": "/", "description": "Host serving this documentation"}],
        "security": [],
        "tags": [
            {"name": "Service", "description": "Deployment and engine metadata."},
            {"name": "Detection", "description": "Review suspicious text artifacts."},
            {"name": "Unicode", "description": "Unicode normalization and identity review."},
            {"name": "Text", "description": "Text-unit measurements."},
            {"name": "JSON", "description": "JSON syntax validation."},
        ],
        "paths": paths,
        "components": {
            "headers": {
                "RequestId": {
                    "description": "Opaque request identifier.",
                    "schema": ref("RequestId"),
                }
            },
            "schemas": build_schemas(),
            "responses": {
                "InvalidRequest": error_response(
                    "invalid_request", 400, "The query or request is invalid."
                ),
                "AnalysisBadRequest": error_response(
                    "invalid_request",
                    400,
                    "The strict envelope, UTF-8 envelope, Base64, or hidden profile is invalid.",
                ),
                "MethodNotAllowedGet": error_response(
                    "invalid_request", 405, "Only GET is allowed."
                ),
                "MethodNotAllowedPost": error_response(
                    "invalid_request", 405, "Only POST and CORS OPTIONS are allowed."
                ),
                "InputTooLarge": error_response(
                    "input_too_large", 413, "The envelope or decoded input exceeds a limit."
                ),
                "UnsupportedRequestEncoding": error_response(
                    "unsupported_media_type",
                    415,
                    "The media type or content encoding is unsupported.",
                ),
                "RateLimited": error_response(
                    "rate_limited", 429, "The per-process anonymous quota is exhausted."
                ),
                "InternalError": error_response(
                    "internal_error", 500, "The API could not complete the request."
                ),
                "LimiterUnavailable": error_response(
                    "limiter_unavailable", 503, "The anonymous limiter failed closed."
                ),
            },
        },
    }


def main() -> None:
    OUTPUT_PATH.write_text(
        json.dumps(build_document(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
