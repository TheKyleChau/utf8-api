"""Shared Unicode helpers and the hidden-character analysis engine."""

import unicodedata
from collections.abc import Iterator
from typing import Any

DETAIL_LIMIT = 500
ENGINE_VERSION = "0.2.0"
RULESET_VERSION = "hidden-2026-08-08"
UNICODE_VERSION = unicodedata.unidata_version

RULES: dict[int, dict[str, str]] = {
    0x00A0: {
        "rule": "whitespace.no_break_space",
        "category": "whitespace",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Non-breaking space",
        "label": "non-breaking space",
        "explanation": (
            "This space looks ordinary but prevents a line break and can affect exact matching."
        ),
    },
    0x00AD: {
        "rule": "hidden.soft_hyphen",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Soft hyphen",
        "label": "soft hyphen",
        "explanation": (
            "This discretionary hyphen is normally invisible unless a line breaks at its position."
        ),
    },
    0x034F: {
        "rule": "hidden.combining_grapheme_joiner",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Combining grapheme joiner",
        "label": "combining grapheme joiner",
        "explanation": (
            "This invisible format character can affect canonical ordering and text comparison."
        ),
    },
    0x061C: {
        "rule": "bidi.arabic_letter_mark",
        "category": "bidirectional",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Arabic letter mark",
        "label": "Arabic letter mark (bidirectional control)",
        "explanation": "This invisible mark influences the direction of adjacent text.",
    },
    0x200B: {
        "rule": "hidden.zero_width_space",
        "category": "hidden_text",
        "severity": "warning",
        "title": "Zero-width space",
        "label": "zero-width space",
        "explanation": (
            "This character has no visible width and can separate otherwise adjacent text."
        ),
    },
    0x200C: {
        "rule": "hidden.zero_width_non_joiner",
        "category": "hidden_text",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Zero-width non-joiner",
        "label": "zero-width non-joiner",
        "explanation": (
            "This character can intentionally prevent joining behavior in scripts that use "
            "contextual forms."
        ),
    },
    0x200D: {
        "rule": "hidden.zero_width_joiner",
        "category": "hidden_text",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Zero-width joiner",
        "label": "zero-width joiner",
        "explanation": (
            "This character can intentionally request joining behavior in text and emoji sequences."
        ),
    },
    0x200E: {
        "rule": "bidi.left_to_right_mark",
        "category": "bidirectional",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Left-to-right mark",
        "label": "left-to-right mark (bidirectional control)",
        "explanation": "This invisible mark influences the direction of adjacent text.",
    },
    0x200F: {
        "rule": "bidi.right_to_left_mark",
        "category": "bidirectional",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Right-to-left mark",
        "label": "right-to-left mark (bidirectional control)",
        "explanation": "This invisible mark influences the direction of adjacent text.",
    },
    0x2060: {
        "rule": "hidden.word_joiner",
        "category": "hidden_text",
        "severity": "warning",
        "title": "Word joiner",
        "label": "word joiner",
        "explanation": "This invisible character prevents a line break at its position.",
    },
    0x2061: {
        "rule": "hidden.function_application",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Function application",
        "label": "function application (invisible operator)",
        "explanation": (
            "This invisible mathematical operator distinguishes function application from "
            "multiplication."
        ),
    },
    0x2062: {
        "rule": "hidden.invisible_times",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Invisible times",
        "label": "invisible times operator",
        "explanation": "This invisible mathematical operator represents multiplication.",
    },
    0x2063: {
        "rule": "hidden.invisible_separator",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Invisible separator",
        "label": "invisible separator",
        "explanation": "This invisible mathematical operator separates adjacent expressions.",
    },
    0x2064: {
        "rule": "hidden.invisible_plus",
        "category": "formatting",
        "severity": "information",
        "identifier_severity": "warning",
        "title": "Invisible plus",
        "label": "invisible plus operator",
        "explanation": "This invisible mathematical operator represents addition.",
    },
    0xFEFF: {
        "rule": "hidden.byte_order_mark",
        "category": "hidden_text",
        "severity": "warning",
        "title": "Byte order mark or zero-width no-break space",
        "label": "byte order mark or zero-width no-break space",
        "explanation": (
            "Inside decoded text this character is invisible and may be an unexpected byte order "
            "mark."
        ),
    },
}

FILLERS = {
    0x115F: "Hangul choseong filler",
    0x1160: "Hangul jungseong filler",
    0x3164: "Hangul filler",
    0xFFA0: "Halfwidth Hangul filler",
}


def format_code_point(code_point: int) -> str:
    return f"U+{code_point:04X}"


def escape_code_point(code_point: int) -> str:
    if code_point == 0x09:
        return r"\t"
    if code_point == 0x0A:
        return r"\n"
    if code_point == 0x0D:
        return r"\r"
    if code_point <= 0xFFFF:
        return f"\\u{code_point:04X}"
    return f"\\u{{{code_point:X}}}"


def unicode_items(text: str) -> Iterator[dict[str, Any]]:
    utf16_index = 0
    for character in text:
        code_point = ord(character)
        utf16_length = 2 if code_point > 0xFFFF else 1
        yield {
            "character": character,
            "code_point": code_point,
            "is_scalar": not 0xD800 <= code_point <= 0xDFFF,
            "utf16_index": utf16_index,
            "utf16_length": utf16_length,
        }
        utf16_index += utf16_length


def control_rule(code_point: int) -> dict[str, str] | None:
    is_control = (
        0x00 <= code_point <= 0x1F
        and code_point not in {0x09, 0x0A, 0x0D}
    ) or 0x7F <= code_point <= 0x9F
    if not is_control:
        return None
    terminal_relevant = code_point in {0x00, 0x08, 0x1B, 0x7F, 0x9B}
    return {
        "rule": f"control.{code_point:04X}",
        "category": "control",
        "severity": "error" if terminal_relevant else "warning",
        "title": "Null control" if code_point == 0x00 else "C0 or C1 control character",
        "label": "C0/C1 control character",
        "explanation": (
            "This control can terminate data or affect terminal interpretation and should be "
            "reviewed before use."
            if terminal_relevant
            else "This non-printing control can affect text processing or transport behavior."
        ),
    }


def bidi_rule(code_point: int) -> dict[str, str] | None:
    names = {
        0x202A: ("left_to_right_embedding", "Left-to-right embedding control"),
        0x202B: ("right_to_left_embedding", "Right-to-left embedding control"),
        0x202C: ("pop_directional_formatting", "Pop directional formatting control"),
        0x202D: ("left_to_right_override", "Left-to-right override control"),
        0x202E: ("right_to_left_override", "Right-to-left override control"),
        0x2066: ("left_to_right_isolate", "Left-to-right isolate control"),
        0x2067: ("right_to_left_isolate", "Right-to-left isolate control"),
        0x2068: ("first_strong_isolate", "First-strong isolate control"),
        0x2069: ("pop_directional_isolate", "Pop directional isolate control"),
    }
    match = names.get(code_point)
    if match:
        is_override = code_point in {0x202D, 0x202E}
        is_isolate = code_point >= 0x2066
        return {
            "rule": f"bidi.{match[0]}",
            "category": "bidirectional",
            "severity": "error" if is_override else ("information" if is_isolate else "warning"),
            "identifier_severity": "error" if is_override else "warning",
            "title": match[1],
            "label": match[1].lower(),
            "explanation": (
                "This invisible override can make displayed character order differ from logical "
                "order."
                if is_override
                else "This invisible control changes how surrounding text is ordered for display."
            ),
        }
    if 0x206A <= code_point <= 0x206F:
        return {
            "rule": "bidi.deprecated_formatting_control",
            "category": "bidirectional",
            "severity": "warning",
            "identifier_severity": "error",
            "title": "Deprecated bidirectional formatting control",
            "label": "deprecated bidirectional formatting control",
            "explanation": (
                "This deprecated invisible control can change how surrounding text is displayed."
            ),
        }
    return None


def generated_rule(code_point: int) -> dict[str, str] | None:
    filler = FILLERS.get(code_point)
    if filler:
        return {
            "rule": "hidden.filler",
            "category": "hidden_text",
            "severity": "warning",
            "title": filler,
            "label": filler.lower(),
            "explanation": "This character is rendered as an invisible filler in normal text.",
        }
    if 0xFE00 <= code_point <= 0xFE0F:
        return {
            "rule": "format.variation_selector",
            "category": "formatting",
            "severity": "information",
            "identifier_severity": "warning",
            "title": "Variation selector",
            "label": "variation selector",
            "explanation": (
                "This invisible selector can intentionally request a different presentation for "
                "the preceding character."
            ),
        }
    if 0xE0100 <= code_point <= 0xE01EF:
        return {
            "rule": "format.supplementary_variation_selector",
            "category": "formatting",
            "severity": "information",
            "identifier_severity": "warning",
            "title": "Supplementary variation selector",
            "label": "supplementary variation selector",
            "explanation": (
                "This invisible selector can intentionally request a registered variation of the "
                "preceding character."
            ),
        }
    if 0xE0000 <= code_point <= 0xE007F:
        return {
            "rule": "hidden.tag_character",
            "category": "hidden_text",
            "severity": "warning",
            "identifier_severity": "error",
            "title": "Unicode tag character",
            "label": "Unicode tag character",
            "explanation": (
                "This tag character is normally invisible and can carry hidden tag information."
            ),
        }
    return bidi_rule(code_point) or control_rule(code_point)


def rule_for(code_point: int, profile: str) -> dict[str, str] | None:
    source = RULES.get(code_point) or generated_rule(code_point)
    if source is None:
        return None
    rule = source.copy()
    if profile == "identifier" and "identifier_severity" in source:
        rule["severity"] = source["identifier_severity"]
    return rule


def hidden_label(code_point: int) -> str | None:
    rule = rule_for(code_point, "general")
    return rule["label"] if rule else None


def utf8_byte_values(code_point: int, is_scalar: bool) -> list[int]:
    if not is_scalar:
        return [0xEF, 0xBF, 0xBD]
    if code_point <= 0x7F:
        return [code_point]
    if code_point <= 0x7FF:
        return [0xC0 | (code_point >> 6), 0x80 | (code_point & 0x3F)]
    if code_point <= 0xFFFF:
        return [
            0xE0 | (code_point >> 12),
            0x80 | ((code_point >> 6) & 0x3F),
            0x80 | (code_point & 0x3F),
        ]
    return [
        0xF0 | (code_point >> 18),
        0x80 | ((code_point >> 12) & 0x3F),
        0x80 | ((code_point >> 6) & 0x3F),
        0x80 | (code_point & 0x3F),
    ]


def contains_unpaired_surrogate(text: str) -> bool:
    return any(not item["is_scalar"] for item in unicode_items(text))


def analyze_hidden(text: str, profile: str = "general") -> dict[str, Any]:
    byte_index = 0
    scalar_index = 0
    utf16_count = 0
    line = 1
    column = 1
    previous_was_carriage_return = False
    total = 0
    scalar_count = 0
    findings: list[dict[str, Any]] = []

    for item in unicode_items(text):
        code_point = item["code_point"]
        encoded = utf8_byte_values(code_point, item["is_scalar"])
        rule = rule_for(code_point, profile)
        if item["is_scalar"]:
            scalar_count += 1

        if rule:
            total += 1
            if len(findings) < DETAIL_LIMIT:
                findings.append(
                    {
                        **item,
                        "id": f"f_{total}",
                        **rule,
                        "location": {
                            "byte_start": byte_index,
                            "byte_end": byte_index + len(encoded),
                            "utf16_start": item["utf16_index"],
                            "utf16_end": item["utf16_index"] + item["utf16_length"],
                            "scalar_start": scalar_index,
                            "scalar_end": scalar_index + 1,
                            "line": line,
                            "column": column,
                        },
                        "observed": {
                            "escaped": escape_code_point(code_point),
                            "code_points": [format_code_point(code_point)],
                            "utf8_hex": " ".join(f"{byte:02X}" for byte in encoded),
                        },
                    }
                )

        byte_index += len(encoded)
        scalar_index += 1
        utf16_count += item["utf16_length"]
        if code_point == 0x0D:
            line += 1
            column = 1
            previous_was_carriage_return = True
        elif code_point == 0x0A:
            if not previous_was_carriage_return:
                line += 1
            column = 1
            previous_was_carriage_return = False
        else:
            column += 1
            previous_was_carriage_return = False

    return {
        "findings": findings,
        "total": total,
        "metrics": {
            "bytes": byte_index,
            "utf16_code_units": utf16_count,
            "unicode_scalars": scalar_count,
            "lines": line,
        },
    }
