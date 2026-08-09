"""Privacy-conscious Unicode review helpers built on the Python standard library.

The public functions in this module return JSON-serializable dictionaries and
never include the submitted string verbatim.  Character excerpts are represented
as code points, escapes, UTF-8 bytes, Unicode names, categories, and scripts.

Script detection and confusable matching are intentionally conservative.  Python's
``unicodedata`` module does not expose the Unicode Script or UTS #39 confusables
properties, so this module derives scripts from Unicode character names and uses a
small, versioned set of common Greek/Cyrillic lookalikes for ASCII Latin letters.
It is a review aid, not a UTS #39 conformance implementation.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.engine import DETAIL_LIMIT

NORMALIZATION_FORMS = ("NFC", "NFD", "NFKC", "NFKD")
CONFUSABLE_DATA_VERSION = "curated-greek-cyrillic-to-ascii-2026-08-09"

# Common cross-script lookalikes used in identifiers.  This is deliberately a
# review-oriented subset rather than an incomplete claim of UTS #39 coverage.
_ASCII_CONFUSABLES: dict[str, str] = {
    # Cyrillic capitals.
    "А": "A",
    "В": "B",
    "С": "C",
    "Е": "E",
    "Н": "H",
    "І": "I",
    "Ј": "J",
    "К": "K",
    "М": "M",
    "О": "O",
    "Р": "P",
    "Ѕ": "S",
    "Т": "T",
    "Х": "X",
    "Ү": "Y",
    # Cyrillic lowercase.
    "а": "a",
    "с": "c",
    "е": "e",
    "і": "i",
    "ј": "j",
    "о": "o",
    "р": "p",
    "ѕ": "s",
    "х": "x",
    "у": "y",
    "ӏ": "l",
    # Greek capitals.
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    # Greek lowercase forms that are commonly rendered like Latin letters.
    "α": "a",
    "ε": "e",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
}

# Markers found in character names.  They cover the scripts most often seen in
# identifiers and ordinary text; unknown/new scripts are reported as ``Unknown``
# rather than guessed.  Common punctuation, symbols, and controls are handled
# before this table.
_SCRIPT_NAME_MARKERS: tuple[tuple[str, str], ...] = (
    ("CANADIAN SYLLABICS", "Canadian_Aboriginal"),
    ("CJK UNIFIED IDEOGRAPH", "Han"),
    ("CJK COMPATIBILITY IDEOGRAPH", "Han"),
    ("IDEOGRAPHIC", "Han"),
    ("HIRAGANA", "Hiragana"),
    ("KATAKANA", "Katakana"),
    ("BOPOMOFO", "Bopomofo"),
    ("HANGUL", "Hangul"),
    ("LATIN", "Latin"),
    ("GREEK", "Greek"),
    ("CYRILLIC", "Cyrillic"),
    ("ARMENIAN", "Armenian"),
    ("HEBREW", "Hebrew"),
    ("ARABIC", "Arabic"),
    ("SYRIAC", "Syriac"),
    ("THAANA", "Thaana"),
    ("NKO", "Nko"),
    ("SAMARITAN", "Samaritan"),
    ("MANDAIC", "Mandaic"),
    ("DEVANAGARI", "Devanagari"),
    ("BENGALI", "Bengali"),
    ("GURMUKHI", "Gurmukhi"),
    ("GUJARATI", "Gujarati"),
    ("ORIYA", "Oriya"),
    ("ODIA", "Oriya"),
    ("TAMIL", "Tamil"),
    ("TELUGU", "Telugu"),
    ("KANNADA", "Kannada"),
    ("MALAYALAM", "Malayalam"),
    ("SINHALA", "Sinhala"),
    ("THAI", "Thai"),
    ("LAO", "Lao"),
    ("TIBETAN", "Tibetan"),
    ("MYANMAR", "Myanmar"),
    ("GEORGIAN", "Georgian"),
    ("ETHIOPIC", "Ethiopic"),
    ("CHEROKEE", "Cherokee"),
    ("OGHAM", "Ogham"),
    ("RUNIC", "Runic"),
    ("TAGALOG", "Tagalog"),
    ("HANUNOO", "Hanunoo"),
    ("BUHID", "Buhid"),
    ("TAGBANWA", "Tagbanwa"),
    ("KHMER", "Khmer"),
    ("MONGOLIAN", "Mongolian"),
    ("YI SYLLABLE", "Yi"),
    ("YI RADICAL", "Yi"),
    ("VAI", "Vai"),
    ("BAMUM", "Bamum"),
    ("TIFINAGH", "Tifinagh"),
    ("LISU", "Lisu"),
    ("JAVANESE", "Javanese"),
    ("BALINESE", "Balinese"),
    ("SUNDANESE", "Sundanese"),
    ("LEPCHA", "Lepcha"),
    ("OL CHIKI", "Ol_Chiki"),
    ("MEETEI MAYEK", "Meetei_Mayek"),
    ("ADLAM", "Adlam"),
    ("OSMANYA", "Osmanya"),
    ("DESERET", "Deseret"),
)

_EXPECTED_UTF8_LENGTH = {
    **{value: 2 for value in range(0xC2, 0xE0)},
    **{value: 3 for value in range(0xE0, 0xF0)},
    **{value: 4 for value in range(0xF0, 0xF5)},
}

# Japanese, Chinese, and Korean commonly use these combinations as one writing
# system.  They remain visible in the script summary but do not by themselves
# generate a suspicious mixed-script finding.
_EXPECTED_SCRIPT_COMBINATIONS = (
    frozenset({"Han", "Hiragana", "Katakana"}),
    frozenset({"Han", "Bopomofo"}),
    frozenset({"Han", "Hangul"}),
)


@dataclass(frozen=True)
class _Offsets:
    byte: list[int]
    utf16: list[int]
    line: list[int]
    column: list[int]


def _validate_text(text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
        raise ValueError("text must contain Unicode scalar values only")


def _offsets(text: str) -> _Offsets:
    byte = [0]
    utf16 = [0]
    line = [1]
    column = [1]
    current_line = 1
    current_column = 1
    previous_was_carriage_return = False

    for character in text:
        code_point = ord(character)
        byte.append(byte[-1] + len(character.encode("utf-8")))
        utf16.append(utf16[-1] + (2 if code_point > 0xFFFF else 1))

        if character == "\r":
            current_line += 1
            current_column = 1
            previous_was_carriage_return = True
        elif character == "\n":
            if not previous_was_carriage_return:
                current_line += 1
            current_column = 1
            previous_was_carriage_return = False
        else:
            current_column += 1
            previous_was_carriage_return = False
        line.append(current_line)
        column.append(current_column)

    return _Offsets(byte=byte, utf16=utf16, line=line, column=column)


def _location(offsets: _Offsets, start: int, end: int) -> dict[str, int]:
    return {
        "byte_start": offsets.byte[start],
        "byte_end": offsets.byte[end],
        "utf16_start": offsets.utf16[start],
        "utf16_end": offsets.utf16[end],
        "scalar_start": start,
        "scalar_end": end,
        "line": offsets.line[start],
        "column": offsets.column[start],
        "line_end": offsets.line[end],
        "column_end": offsets.column[end],
    }


def _metrics(text: str, offsets: _Offsets | None = None) -> dict[str, int]:
    positions = offsets or _offsets(text)
    return {
        "bytes": positions.byte[-1],
        "unicode_scalars": len(text),
        "utf16_code_units": positions.utf16[-1],
        "lines": positions.line[-1],
    }


def _escape(character: str) -> str:
    code_point = ord(character)
    if code_point <= 0xFFFF:
        return f"\\u{code_point:04X}"
    return f"\\U{code_point:08X}"


def _script(character: str) -> str:
    category = unicodedata.category(character)
    name = unicodedata.name(character, "")

    # Common includes separators, punctuation, symbols, controls, private-use,
    # and surrogates (the latter are rejected at the public boundary).
    if category[0] in {"C", "P", "S", "Z"}:
        return "Common"

    for marker, script in _SCRIPT_NAME_MARKERS:
        if marker in name:
            return script

    if category in {"Mn", "Me"} or name.startswith("COMBINING "):
        return "Inherited"
    if category == "Cn":
        return "Unknown"
    return "Common" if category[0] == "N" else "Unknown"


def _character_detail(
    character: str,
    *,
    offsets: _Offsets | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    encoded = character.encode("utf-8")
    detail: dict[str, Any] = {
        "escaped": _escape(character),
        "code_point": f"U+{ord(character):04X}",
        "utf8_hex": " ".join(f"{byte:02X}" for byte in encoded),
        "name": unicodedata.name(character, "UNNAMED"),
        "category": unicodedata.category(character),
        "script": _script(character),
    }
    if offsets is not None and index is not None:
        detail["location"] = _location(offsets, index, index + 1)
    return detail


def _bounded_character_details(
    text: str,
    start: int,
    end: int,
    offsets: _Offsets,
) -> dict[str, Any]:
    returned_end = min(end, start + DETAIL_LIMIT)
    return {
        "characters": [
            _character_detail(text[index], offsets=offsets, index=index)
            for index in range(start, returned_end)
        ],
        "total": end - start,
        "returned": returned_end - start,
        "truncated": returned_end < end,
    }


def _legacy_byte(character: str) -> int | None:
    code_point = ord(character)
    if code_point <= 0xFF:
        return code_point
    try:
        encoded = character.encode("cp1252")
    except UnicodeEncodeError:
        return None
    return encoded[0] if len(encoded) == 1 else None


def _mojibake_candidate(text: str, start: int) -> tuple[int, str, bytes] | None:
    first = _legacy_byte(text[start])
    if first is None:
        return None
    length = _EXPECTED_UTF8_LENGTH.get(first)
    if length is None or start + length > len(text):
        return None

    values: list[int] = []
    for character in text[start : start + length]:
        value = _legacy_byte(character)
        if value is None:
            return None
        values.append(value)
    if any(not 0x80 <= value <= 0xBF for value in values[1:]):
        return None

    source_bytes = bytes(values)
    try:
        repaired = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if len(repaired) != 1:
        return None
    return length, repaired, source_bytes


def detect_mojibake(text: str) -> dict[str, Any]:
    """Flag likely UTF-8-as-Latin-1/Windows-1252 artifacts and U+FFFD.

    The detector recognizes complete UTF-8 byte sequences whose bytes are being
    displayed as Latin-1 or Windows-1252 characters.  It intentionally does not
    flag an isolated marker such as a genuine ``U+00E2`` without a complete byte
    sequence.  Detail findings are capped at :data:`app.engine.DETAIL_LIMIT`.
    """

    _validate_text(text)
    offsets = _offsets(text)
    findings: list[dict[str, Any]] = []
    total = 0
    index = 0

    while index < len(text):
        if text[index] == "\ufffd":
            total += 1
            if len(findings) < DETAIL_LIMIT:
                findings.append(
                    {
                        "id": f"mojibake_{total}",
                        "rule": "mojibake.replacement_character",
                        "category": "mojibake",
                        "severity": "warning",
                        "title": "Unicode replacement character",
                        "location": _location(offsets, index, index + 1),
                        "observed": {
                            "characters": [
                                _character_detail(text[index], offsets=offsets, index=index)
                            ]
                        },
                        "explanation": (
                            "U+FFFD commonly marks data that could not be decoded; review the "
                            "original bytes and decoder settings."
                        ),
                    }
                )
            index += 1
            continue

        candidate = _mojibake_candidate(text, index)
        if candidate is None:
            index += 1
            continue

        length, repaired, legacy_bytes = candidate
        total += 1
        if len(findings) < DETAIL_LIMIT:
            findings.append(
                {
                    "id": f"mojibake_{total}",
                    "rule": "mojibake.utf8_bytes_as_legacy_text",
                    "category": "mojibake",
                    "severity": "warning",
                    "title": "Possible UTF-8 bytes decoded as a legacy encoding",
                    "location": _location(offsets, index, index + length),
                    "observed": {
                        "characters": [
                            _character_detail(
                                text[character_index],
                                offsets=offsets,
                                index=character_index,
                            )
                            for character_index in range(index, index + length)
                        ],
                        "interpreted_bytes_hex": " ".join(
                            f"{byte:02X}" for byte in legacy_bytes
                        ),
                    },
                    "possible_intended_character": _character_detail(repaired),
                    "explanation": (
                        "These displayed characters map to one well-formed UTF-8 sequence when "
                        "read as Latin-1 or Windows-1252 bytes."
                    ),
                }
            )
        index += length

    return {
        "check": "mojibake",
        "unicode_version": unicodedata.unidata_version,
        "metrics": _metrics(text, offsets),
        "summary": {
            "total": total,
            "returned": len(findings),
            "truncated": total > len(findings),
        },
        "findings": findings,
    }


def _changed_envelope(source: str, normalized: str) -> tuple[int, int, int, int]:
    prefix = 0
    shared_limit = min(len(source), len(normalized))
    while prefix < shared_limit and source[prefix] == normalized[prefix]:
        prefix += 1

    source_suffix = len(source)
    normalized_suffix = len(normalized)
    while (
        source_suffix > prefix
        and normalized_suffix > prefix
        and source[source_suffix - 1] == normalized[normalized_suffix - 1]
    ):
        source_suffix -= 1
        normalized_suffix -= 1
    return prefix, source_suffix, prefix, normalized_suffix


def check_normalization(text: str) -> dict[str, Any]:
    """Compare *text* with NFC, NFD, NFKC, and NFKD without echoing it.

    Each differing form produces one finding covering the smallest shared-prefix/
    shared-suffix envelope that contains every change.  Character detail within
    that envelope is bounded by ``DETAIL_LIMIT``.
    """

    _validate_text(text)
    source_offsets = _offsets(text)
    forms: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, Any]] = []

    for form in NORMALIZATION_FORMS:
        normalized = unicodedata.normalize(form, text)
        normalized_offsets = _offsets(normalized)
        is_normalized = normalized == text
        forms[form] = {
            "is_normalized": is_normalized,
            "metrics": _metrics(normalized, normalized_offsets),
        }
        if is_normalized:
            continue

        source_start, source_end, normalized_start, normalized_end = _changed_envelope(
            text, normalized
        )
        findings.append(
            {
                "id": f"normalization_{len(findings) + 1}",
                "rule": f"normalization.not_{form.lower()}",
                "category": "normalization",
                "severity": "information",
                "title": f"Text differs from {form}",
                "form": form,
                "location": _location(source_offsets, source_start, source_end),
                "observed": _bounded_character_details(
                    text, source_start, source_end, source_offsets
                ),
                "normalized": _bounded_character_details(
                    normalized,
                    normalized_start,
                    normalized_end,
                    normalized_offsets,
                ),
                "explanation": (
                    f"Normalizing with Unicode {form} changes the code-point sequence in this "
                    "range. Normalization can affect exact matching and identifier comparison."
                ),
            }
        )

    return {
        "check": "normalization",
        "unicode_version": unicodedata.unidata_version,
        "metrics": _metrics(text, source_offsets),
        "forms": forms,
        "summary": {
            "total": len(findings),
            "returned": len(findings),
            "truncated": False,
        },
        "findings": findings,
    }


def _expected_script_combination(scripts: set[str]) -> bool:
    return any(scripts.issubset(expected) for expected in _EXPECTED_SCRIPT_COMBINATIONS)


def review_mixed_scripts(text: str) -> dict[str, Any]:
    """Review mixed writing systems and curated Greek/Cyrillic lookalikes.

    Common/Inherited characters do not create a mixed-script condition.  Familiar
    Han/Hiragana/Katakana, Han/Bopomofo, and Han/Hangul combinations are summarized
    but not automatically treated as suspicious.  Curated confusables are reported
    when their ASCII Latin target script also occurs in the input.
    """

    _validate_text(text)
    offsets = _offsets(text)
    script_by_index = [_script(character) for character in text]
    significant = [
        (index, script)
        for index, (character, script) in enumerate(zip(text, script_by_index, strict=True))
        if unicodedata.category(character).startswith("L")
        and script not in {"Common", "Inherited", "Unknown"}
    ]
    counts = Counter(script for _, script in significant)
    scripts = set(counts)
    first_index = {
        script: next(index for index, item_script in significant if item_script == script)
        for script in scripts
    }
    dominant_script = (
        min(scripts, key=lambda script: (-counts[script], first_index[script]))
        if scripts
        else None
    )
    is_mixed_script = len(scripts) > 1
    expected_combination = is_mixed_script and _expected_script_combination(scripts)
    mixed_script_requires_review = is_mixed_script and not expected_combination

    suspicious_indices: set[int] = set()
    rules: dict[int, str] = {}
    if mixed_script_requires_review and dominant_script is not None:
        for index, script in significant:
            if script != dominant_script:
                suspicious_indices.add(index)
                rules[index] = "mixed_script.character"

    # A curated lookalike is contextually suspicious when Latin letters are also
    # present.  Include it even if its non-Latin script happens to be dominant.
    if "Latin" in scripts:
        for index, character in enumerate(text):
            if character in _ASCII_CONFUSABLES and script_by_index[index] != "Latin":
                suspicious_indices.add(index)
                rules[index] = "confusable.curated_ascii_lookalike"

    ordered_indices = sorted(suspicious_indices)
    findings: list[dict[str, Any]] = []
    for finding_number, index in enumerate(ordered_indices, start=1):
        if len(findings) >= DETAIL_LIMIT:
            break
        character = text[index]
        target = _ASCII_CONFUSABLES.get(character)
        rule = rules[index]
        finding: dict[str, Any] = {
            "id": f"script_{finding_number}",
            "rule": rule,
            "category": "confusable" if target is not None else "mixed_script",
            "severity": "warning",
            "title": (
                "Curated cross-script lookalike"
                if target is not None
                else "Character from a different writing system"
            ),
            "location": _location(offsets, index, index + 1),
            "observed": _character_detail(character, offsets=offsets, index=index),
            "explanation": (
                "This non-Latin character resembles an ASCII Latin letter and appears in text "
                "that also uses Latin. Review it in names, links, and identifiers."
                if target is not None
                else "This character uses a different script from the dominant writing system. "
                "Mixed scripts can be legitimate but deserve review in identifiers."
            ),
        }
        if target is not None:
            finding["looks_like"] = _character_detail(target)
            finding["confusable_data_version"] = CONFUSABLE_DATA_VERSION
        findings.append(finding)

    script_summary = [
        {
            "script": script,
            "count": counts[script],
            "first_scalar": first_index[script],
        }
        for script in sorted(scripts, key=lambda script: first_index[script])
    ]
    total = len(ordered_indices)
    return {
        "check": "mixed_scripts_and_confusables",
        "unicode_version": unicodedata.unidata_version,
        "confusable_data": {
            "kind": "curated_subset",
            "version": CONFUSABLE_DATA_VERSION,
            "source_scripts": ["Cyrillic", "Greek"],
            "target_script": "ASCII Latin",
            "uts39_complete": False,
        },
        "metrics": _metrics(text, offsets),
        "scripts": script_summary,
        "dominant_script": dominant_script,
        "is_mixed_script": is_mixed_script,
        "expected_script_combination": expected_combination,
        "review_recommended": total > 0,
        "summary": {
            "total": total,
            "returned": len(findings),
            "truncated": total > len(findings),
        },
        "findings": findings,
    }
