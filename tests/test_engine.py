from app.engine import (
    DETAIL_LIMIT,
    analyze_hidden,
    contains_unpaired_surrogate,
    escape_code_point,
    format_code_point,
    hidden_label,
    utf8_byte_values,
)


def test_code_point_formatting_and_escaping() -> None:
    assert format_code_point(0x0A) == "U+000A"
    assert format_code_point(0x1F600) == "U+1F600"
    assert escape_code_point(0x09) == r"\t"
    assert escape_code_point(0x0A) == r"\n"
    assert escape_code_point(0x0D) == r"\r"
    assert escape_code_point(0x200B) == r"\u200B"
    assert escape_code_point(0xE0100) == r"\u{E0100}"


def test_utf8_byte_values_match_scalar_encoding_and_surrogate_replacement() -> None:
    assert utf8_byte_values(ord("A"), True) == [0x41]
    assert utf8_byte_values(ord("é"), True) == [0xC3, 0xA9]
    assert utf8_byte_values(ord("€"), True) == [0xE2, 0x82, 0xAC]
    assert utf8_byte_values(ord("😀"), True) == [0xF0, 0x9F, 0x98, 0x80]
    assert utf8_byte_values(0xD800, False) == [0xEF, 0xBF, 0xBD]


def test_known_and_generated_rules() -> None:
    assert hidden_label(0x200B) == "zero-width space"
    analysis = analyze_hidden("\u115f\ufe0f\U000e0100\U000e0001\u202e\x00")
    assert [finding["rule"] for finding in analysis["findings"]] == [
        "hidden.filler",
        "format.variation_selector",
        "format.supplementary_variation_selector",
        "hidden.tag_character",
        "bidi.right_to_left_override",
        "control.0000",
    ]


def test_analysis_tracks_utf8_utf16_scalar_and_line_offsets() -> None:
    analysis = analyze_hidden("A😀\r\nB\u200b")
    finding = analysis["findings"][0]
    assert analysis["metrics"] == {
        "bytes": 11,
        "utf16_code_units": 7,
        "unicode_scalars": 6,
        "lines": 2,
    }
    assert finding["location"] == {
        "byte_start": 8,
        "byte_end": 11,
        "utf16_start": 6,
        "utf16_end": 7,
        "scalar_start": 5,
        "scalar_end": 6,
        "line": 2,
        "column": 2,
    }
    assert finding["observed"] == {
        "escaped": r"\u200B",
        "code_points": ["U+200B"],
        "utf8_hex": "E2 80 8B",
    }


def test_identifier_profile_overrides_severity() -> None:
    general = analyze_hidden("\u00a0\u200c", "general")
    identifier = analyze_hidden("\u00a0\u200c", "identifier")
    assert [item["severity"] for item in general["findings"]] == [
        "information",
        "information",
    ]
    assert [item["severity"] for item in identifier["findings"]] == [
        "warning",
        "warning",
    ]


def test_unpaired_surrogate_detection() -> None:
    assert contains_unpaired_surrogate("\ud800")
    assert contains_unpaired_surrogate("\udfff")
    assert not contains_unpaired_surrogate("😀")


def test_detail_limit_counts_all_findings() -> None:
    analysis = analyze_hidden("\u200b" * (DETAIL_LIMIT + 1))
    assert analysis["total"] == DETAIL_LIMIT + 1
    assert len(analysis["findings"]) == DETAIL_LIMIT
    assert analysis["findings"][-1]["id"] == f"f_{DETAIL_LIMIT}"
