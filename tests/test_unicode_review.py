import json

import pytest

from app.engine import DETAIL_LIMIT
from app.unicode_review import (
    CONFUSABLE_DATA_VERSION,
    check_normalization,
    detect_mojibake,
    review_mixed_scripts,
)


def assert_json_serializable(value: object) -> None:
    assert json.loads(json.dumps(value)) == value


def test_ascii_is_clean_for_all_three_reviews() -> None:
    text = "plain ASCII 123"
    mojibake = detect_mojibake(text)
    normalization = check_normalization(text)
    scripts = review_mixed_scripts(text)

    assert mojibake["summary"] == {"total": 0, "returned": 0, "truncated": False}
    assert all(result["is_normalized"] for result in normalization["forms"].values())
    assert normalization["findings"] == []
    assert scripts["scripts"] == [{"script": "Latin", "count": 10, "first_scalar": 0}]
    assert scripts["dominant_script"] == "Latin"
    assert not scripts["is_mixed_script"]
    assert not scripts["review_recommended"]
    assert_json_serializable(mojibake)
    assert_json_serializable(normalization)
    assert_json_serializable(scripts)


def test_mojibake_finds_utf8_decoded_as_latin1_with_exact_offsets() -> None:
    result = detect_mojibake("cafÃ©")

    assert result["summary"] == {"total": 1, "returned": 1, "truncated": False}
    finding = result["findings"][0]
    assert finding["rule"] == "mojibake.utf8_bytes_as_legacy_text"
    assert finding["location"] == {
        "byte_start": 3,
        "byte_end": 7,
        "utf16_start": 3,
        "utf16_end": 5,
        "scalar_start": 3,
        "scalar_end": 5,
        "line": 1,
        "column": 4,
        "line_end": 1,
        "column_end": 6,
    }
    assert finding["observed"]["interpreted_bytes_hex"] == "C3 A9"
    assert [item["code_point"] for item in finding["observed"]["characters"]] == [
        "U+00C3",
        "U+00A9",
    ]
    intended = finding["possible_intended_character"]
    assert intended == {
        "escaped": r"\u00E9",
        "code_point": "U+00E9",
        "utf8_hex": "C3 A9",
        "name": "LATIN SMALL LETTER E WITH ACUTE",
        "category": "Ll",
        "script": "Latin",
    }


def test_mojibake_handles_windows_1252_emoji_and_replacement_character() -> None:
    punctuation = detect_mojibake("â€™")
    assert punctuation["findings"][0]["observed"]["interpreted_bytes_hex"] == "E2 80 99"
    assert punctuation["findings"][0]["possible_intended_character"]["code_point"] == "U+2019"

    emoji = detect_mojibake("ðŸ˜€")
    assert emoji["findings"][0]["observed"]["interpreted_bytes_hex"] == "F0 9F 98 80"
    assert emoji["findings"][0]["possible_intended_character"]["code_point"] == "U+1F600"

    replacement = detect_mojibake("😀�")
    finding = replacement["findings"][0]
    assert finding["rule"] == "mojibake.replacement_character"
    assert finding["location"]["byte_start"] == 4
    assert finding["location"]["scalar_start"] == 1
    assert finding["location"]["utf16_start"] == 2
    assert finding["observed"]["characters"][0]["name"] == "REPLACEMENT CHARACTER"


def test_mojibake_does_not_flag_genuine_isolated_accented_text() -> None:
    assert detect_mojibake("café âge")["findings"] == []


def test_mojibake_detail_list_is_bounded_but_total_is_complete() -> None:
    result = detect_mojibake("�" * (DETAIL_LIMIT + 3))
    assert result["summary"] == {
        "total": DETAIL_LIMIT + 3,
        "returned": DETAIL_LIMIT,
        "truncated": True,
    }
    assert len(result["findings"]) == DETAIL_LIMIT


def test_composed_and_decomposed_accents_report_all_normalization_forms() -> None:
    composed = check_normalization("é")
    assert {form: data["is_normalized"] for form, data in composed["forms"].items()} == {
        "NFC": True,
        "NFD": False,
        "NFKC": True,
        "NFKD": False,
    }
    assert [finding["form"] for finding in composed["findings"]] == ["NFD", "NFKD"]
    nfd = composed["findings"][0]
    assert nfd["location"]["byte_end"] == 2
    assert [item["code_point"] for item in nfd["normalized"]["characters"]] == [
        "U+0065",
        "U+0301",
    ]
    assert [item["script"] for item in nfd["normalized"]["characters"]] == [
        "Latin",
        "Inherited",
    ]

    decomposed = check_normalization("é")
    assert {form: data["is_normalized"] for form, data in decomposed["forms"].items()} == {
        "NFC": False,
        "NFD": True,
        "NFKC": False,
        "NFKD": True,
    }
    assert [finding["form"] for finding in decomposed["findings"]] == ["NFC", "NFKC"]
    nfc = decomposed["findings"][0]
    assert nfc["location"]["byte_end"] == 3
    assert nfc["location"]["scalar_end"] == 2
    assert nfc["location"]["utf16_end"] == 2
    assert [item["code_point"] for item in nfc["normalized"]["characters"]] == ["U+00E9"]


def test_normalization_distinguishes_canonical_and_compatibility_forms() -> None:
    result = check_normalization("①")
    assert {form: data["is_normalized"] for form, data in result["forms"].items()} == {
        "NFC": True,
        "NFD": True,
        "NFKC": False,
        "NFKD": False,
    }
    assert result["forms"]["NFKC"]["metrics"] == {
        "bytes": 1,
        "unicode_scalars": 1,
        "utf16_code_units": 1,
        "lines": 1,
    }
    assert result["findings"][0]["normalized"]["characters"][0]["code_point"] == "U+0031"


def test_normalization_change_location_accounts_for_astral_prefix() -> None:
    result = check_normalization("😀éz")
    finding = next(item for item in result["findings"] if item["form"] == "NFC")
    assert finding["location"] == {
        "byte_start": 4,
        "byte_end": 7,
        "utf16_start": 2,
        "utf16_end": 4,
        "scalar_start": 1,
        "scalar_end": 3,
        "line": 1,
        "column": 2,
        "line_end": 1,
        "column_end": 4,
    }


@pytest.mark.parametrize("text", ["paypal", "Привет", "Ελλάδα"])
def test_legitimate_single_script_text_needs_no_review(text: str) -> None:
    result = review_mixed_scripts(text)
    assert not result["is_mixed_script"]
    assert not result["review_recommended"]
    assert result["findings"] == []


def test_cyrillic_lookalike_in_latin_identifier_is_surfaced() -> None:
    result = review_mixed_scripts("pаypal")
    assert result["is_mixed_script"]
    assert result["dominant_script"] == "Latin"
    assert result["scripts"] == [
        {"script": "Latin", "count": 5, "first_scalar": 0},
        {"script": "Cyrillic", "count": 1, "first_scalar": 1},
    ]
    finding = result["findings"][0]
    assert finding["rule"] == "confusable.curated_ascii_lookalike"
    assert finding["observed"]["name"] == "CYRILLIC SMALL LETTER A"
    assert finding["observed"]["category"] == "Ll"
    assert finding["observed"]["script"] == "Cyrillic"
    assert finding["looks_like"]["code_point"] == "U+0061"
    assert finding["location"]["byte_start"] == 1
    assert finding["location"]["byte_end"] == 3
    assert finding["location"]["scalar_start"] == 1
    assert finding["location"]["utf16_start"] == 1
    assert finding["confusable_data_version"] == CONFUSABLE_DATA_VERSION
    assert result["confusable_data"]["uts39_complete"] is False


def test_greek_lookalike_and_astral_offsets_are_surfaced() -> None:
    result = review_mixed_scripts("😀PΑYPAL")
    finding = result["findings"][0]
    assert finding["observed"]["code_point"] == "U+0391"
    assert finding["looks_like"]["code_point"] == "U+0041"
    assert finding["location"]["byte_start"] == 5
    assert finding["location"]["byte_end"] == 7
    assert finding["location"]["scalar_start"] == 2
    assert finding["location"]["utf16_start"] == 3


def test_expected_east_asian_script_combinations_are_not_flagged() -> None:
    result = review_mixed_scripts("漢字かなカナ")
    assert result["is_mixed_script"]
    assert result["expected_script_combination"]
    assert not result["review_recommended"]
    assert result["findings"] == []


def test_mixed_script_detail_limit_counts_all_suspicious_characters() -> None:
    text = "a" + "а" * (DETAIL_LIMIT + 1)
    result = review_mixed_scripts(text)
    assert result["summary"] == {
        "total": DETAIL_LIMIT + 2,
        "returned": DETAIL_LIMIT,
        "truncated": True,
    }
    assert len(result["findings"]) == DETAIL_LIMIT


def test_all_reviews_handle_the_full_32_kib_ascii_input() -> None:
    text = "a" * (32 * 1024)
    results = [detect_mojibake(text), check_normalization(text), review_mixed_scripts(text)]
    for result in results:
        assert result["metrics"] == {
            "bytes": 32 * 1024,
            "unicode_scalars": 32 * 1024,
            "utf16_code_units": 32 * 1024,
            "lines": 1,
        }
        assert_json_serializable(result)


@pytest.mark.parametrize("analyzer", [detect_mojibake, check_normalization, review_mixed_scripts])
def test_public_analyzers_reject_non_scalars_and_non_strings(analyzer) -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        analyzer("\ud800")
    with pytest.raises(TypeError, match="string"):
        analyzer(None)
