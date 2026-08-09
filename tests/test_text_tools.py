import pytest

from app.engine import DETAIL_LIMIT
from app.text_tools import count_text, inspect_code_points, validate_json


def test_text_counter_reports_all_requested_units() -> None:
    text = "Cafe\u0301 👩🏽\u200d💻\r\nflag"
    assert count_text(text) == {
        "utf8_bytes": 28,
        "unicode_code_points": 16,
        "unicode_scalars": 16,
        "grapheme_clusters": 11,
        "words": 2,
        "lines": 2,
        "javascript_string_units": 19,
    }


def test_text_counter_empty_and_line_semantics() -> None:
    assert count_text("") == {
        "utf8_bytes": 0,
        "unicode_code_points": 0,
        "unicode_scalars": 0,
        "grapheme_clusters": 0,
        "words": 0,
        "lines": 1,
        "javascript_string_units": 0,
    }
    assert count_text("a\r\nb\rc\nd")["lines"] == 4


@pytest.mark.parametrize(
    ("text", "clusters"),
    [
        ("a\u0301", 1),
        ("👩🏽\u200d💻", 1),
        ("🇺🇸🇨🇦", 2),
        ("\r\n", 1),
        ("\u1100\u1161\u11a8", 1),
        ("👍🏿", 1),
        ("\u0600A", 1),
        ("कः", 1),
        ("กำ", 1),
        ("❤️\u200d🔥", 1),
        ("A\u200dB", 2),
        ("🇺\u200d🇸", 2),
        ("🇺🇸🇨", 2),
        ("क्ष", 1),
        ("क्\u200dष", 1),
    ],
)
def test_text_counter_uses_extended_grapheme_clusters(text: str, clusters: int) -> None:
    assert count_text(text)["grapheme_clusters"] == clusters


def test_text_counter_words_are_unicode_aware() -> None:
    assert count_text("can't l’amour Cafe\u0301 中文 123_456 👩")["words"] == 5


@pytest.mark.parametrize(
    ("source", "value_type"),
    [
        ('{"value": [1, true, null]}', "object"),
        ("[]", "array"),
        ('"text"', "string"),
        ("123456789012345678901234567890", "number"),
        ("false", "boolean"),
        ("null", "null"),
    ],
)
def test_json_validator_accepts_every_standard_top_level_type(source: str, value_type: str) -> None:
    assert validate_json(source) == {"valid": True, "value_type": value_type}


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_validator_rejects_non_standard_numbers(constant: str) -> None:
    source = f'["{constant}",\n {constant}]'
    assert validate_json(source) == {
        "valid": False,
        "error": {
            "code": "non_standard_number",
            "message": "JSON numbers cannot be NaN or infinity.",
            "line": 2,
            "column": 2,
            "character_offset": len(constant) + 6,
            "byte_offset": len(constant) + 6,
        },
    }


def test_json_validator_reports_stable_character_and_utf8_byte_offsets() -> None:
    result = validate_json('["é", ]')
    assert result["valid"] is False
    assert result["error"] == {
        "code": "trailing_comma",
        "message": "Trailing commas are not permitted in JSON.",
        "line": 1,
        "column": 5,
        "character_offset": 4,
        "byte_offset": 5,
    }


def test_json_validator_counts_cr_and_crlf_as_line_endings() -> None:
    cr_only = validate_json('["é",\r ]')
    assert cr_only["error"] == {
        "code": "trailing_comma",
        "message": "Trailing commas are not permitted in JSON.",
        "line": 1,
        "column": 5,
        "character_offset": 4,
        "byte_offset": 5,
    }

    after_cr = validate_json('["é"\r true]')
    assert after_cr["error"]["line"] == 2
    assert after_cr["error"]["column"] == 2
    assert after_cr["error"]["byte_offset"] == 7


def test_json_validator_bounds_excessive_nesting() -> None:
    accepted = "[" * 512 + "0" + "]" * 512
    assert validate_json(accepted) == {"valid": True, "value_type": "array"}

    source = "[" * 513 + "0" + "]" * 513
    result = validate_json(source)
    assert result == {
        "valid": False,
        "error": {
            "code": "nesting_too_deep",
            "message": "JSON nesting exceeds the 512-level limit.",
            "line": 1,
            "column": 513,
            "character_offset": 512,
            "byte_offset": 512,
        },
    }


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("", "unexpected_end"),
        ('{"key":', "unexpected_end"),
        ("{'key': 1}", "single_quoted_string"),
        ('{"key" 1}', "expected_colon"),
        ('{"key": 1 "next": 2}', "expected_comma_or_end"),
        ('"\\q"', "invalid_escape"),
        ("[1 // comment\n]", "comment_not_allowed"),
    ],
)
def test_json_validator_classifies_common_syntax_errors(source: str, code: str) -> None:
    result = validate_json(source)
    assert result["valid"] is False
    assert result["error"]["code"] == code
    assert set(result["error"]) == {
        "code",
        "message",
        "line",
        "column",
        "character_offset",
        "byte_offset",
    }


def test_code_point_inspector_reports_unicode_bytes_and_positions() -> None:
    result = inspect_code_points("Aé😀\n\u0301\u200d")
    assert result["summary"] == {"total": 6, "returned": 6, "truncated": False}

    assert result["characters"][0] == {
        "index": 0,
        "code_point": "U+0041",
        "decimal": 65,
        "name": "LATIN CAPITAL LETTER A",
        "category": "Lu",
        "utf8_bytes": [0x41],
        "utf8_hex": "41",
        "position": {
            "byte_start": 0,
            "byte_end": 1,
            "code_point_start": 0,
            "code_point_end": 1,
            "javascript_unit_start": 0,
            "javascript_unit_end": 1,
            "line": 1,
            "column": 1,
        },
        "visible": "A",
    }

    emoji = result["characters"][2]
    assert emoji["code_point"] == "U+1F600"
    assert emoji["name"] == "GRINNING FACE"
    assert emoji["category"] == "So"
    assert emoji["utf8_bytes"] == [0xF0, 0x9F, 0x98, 0x80]
    assert emoji["utf8_hex"] == "F0 9F 98 80"
    assert emoji["position"] == {
        "byte_start": 3,
        "byte_end": 7,
        "code_point_start": 2,
        "code_point_end": 3,
        "javascript_unit_start": 2,
        "javascript_unit_end": 4,
        "line": 1,
        "column": 3,
    }

    line_feed = result["characters"][3]
    assert line_feed["name"] == "LINE FEED"
    assert line_feed["visible"] == r"\n"
    combining = result["characters"][4]
    assert combining["visible"] == "◌\u0301"
    assert combining["position"]["line"] == 2
    assert combining["position"]["column"] == 1
    assert result["characters"][5]["visible"] == r"\u200D"


def test_code_point_inspector_is_bounded_by_shared_detail_limit() -> None:
    result = inspect_code_points("A" * (DETAIL_LIMIT + 2))
    assert result["summary"] == {
        "total": DETAIL_LIMIT + 2,
        "returned": DETAIL_LIMIT,
        "truncated": True,
    }
    assert len(result["characters"]) == DETAIL_LIMIT
    assert result["characters"][-1]["index"] == DETAIL_LIMIT - 1
