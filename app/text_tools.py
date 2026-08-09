"""Unicode text counting, JSON validation, and code-point inspection helpers."""

import json
import unicodedata
from typing import Any

from app.engine import DETAIL_LIMIT, escape_code_point, format_code_point, utf8_byte_values

_JSON_NUMBER = object()

_PREPEND_RANGES = (
    (0x0600, 0x0605),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x0D4E, 0x0D4E),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x111C2, 0x111C3),
    (0x113D1, 0x113D1),
    (0x1193F, 0x1193F),
    (0x11941, 0x11941),
    (0x11A84, 0x11A89),
    (0x11D46, 0x11D46),
    (0x11F02, 0x11F02),
)

_SPACING_MARK_EXCEPTIONS = {0x0E33, 0x0EB3, 0x11B61, 0x11B65, 0x11B67}

# The standard library exposes general categories and names, but not the
# Indic_Conjunct_Break property used by UAX #29's GB9c rule. Keep a small,
# conservative block map and recognize linkers from their assigned Unicode
# names so common Indic conjuncts stay together without another dependency.
_INDIC_SCRIPT_RANGES = (
    (0x0900, 0x097F),
    (0x0980, 0x09FF),
    (0x0A00, 0x0A7F),
    (0x0A80, 0x0AFF),
    (0x0B00, 0x0B7F),
    (0x0B80, 0x0BFF),
    (0x0C00, 0x0C7F),
    (0x0C80, 0x0CFF),
    (0x0D00, 0x0D7F),
    (0x0D80, 0x0DFF),
    (0x1000, 0x109F),
    (0x1780, 0x17FF),
    (0x1A20, 0x1AAF),
    (0xA8E0, 0xA8FF),
    (0xA980, 0xA9DF),
    (0xAA60, 0xAA7F),
    (0xABC0, 0xABFF),
    (0x11000, 0x11FFF),
)

_JSON_NESTING_LIMIT = 512

# Python's standard library does not expose Extended_Pictographic. These ranges
# cover assigned emoji/pictograph blocks and the legacy symbols used in emoji
# ZWJ sequences. They are intentionally consulted only for GB11, not to decide
# whether an individual symbol is a grapheme cluster.
_EXTENDED_PICTOGRAPHIC_RANGES = (
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x21FF),
    (0x2300, 0x23FF),
    (0x25A0, 0x27FF),
    (0x2B00, 0x2BFF),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
    (0x1F000, 0x1FAFF),
    (0x1FC00, 0x1FFFD),
)

_CONTROL_NAMES = {
    0x0000: "NULL",
    0x0007: "ALERT",
    0x0008: "BACKSPACE",
    0x0009: "CHARACTER TABULATION",
    0x000A: "LINE FEED",
    0x000B: "LINE TABULATION",
    0x000C: "FORM FEED",
    0x000D: "CARRIAGE RETURN",
    0x001B: "ESCAPE",
    0x007F: "DELETE",
    0x0085: "NEXT LINE",
}


class _NonStandardJSONNumber(ValueError):
    """Raised internally when the JSON decoder encounters NaN or infinity."""

    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__(token)


def _is_scalar(character: str) -> bool:
    return not 0xD800 <= ord(character) <= 0xDFFF


def _utf8_values(character: str) -> list[int]:
    return utf8_byte_values(ord(character), _is_scalar(character))


def _utf8_length(text: str) -> int:
    # Request validation excludes lone surrogates. Treating one as U+FFFD here
    # keeps this engine helper bounded and consistent with app.engine if it is
    # called directly with an otherwise-unencodable Python string.
    return sum(len(_utf8_values(character)) for character in text)


def _line_count(text: str) -> int:
    """Count CR, LF, and CRLF line endings, with even empty text occupying one line."""
    lines = 1
    index = 0
    while index < len(text):
        if text[index] == "\r":
            lines += 1
            index += 2 if index + 1 < len(text) and text[index + 1] == "\n" else 1
        elif text[index] == "\n":
            lines += 1
            index += 1
        else:
            index += 1
    return lines


def _in_ranges(code_point: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= code_point <= end for start, end in ranges)


def _hangul_grapheme_property(code_point: int) -> str | None:
    if 0x1100 <= code_point <= 0x115F or 0xA960 <= code_point <= 0xA97C:
        return "L"
    if 0x1160 <= code_point <= 0x11A7 or 0xD7B0 <= code_point <= 0xD7C6:
        return "V"
    if 0x11A8 <= code_point <= 0x11FF or 0xD7CB <= code_point <= 0xD7FB:
        return "T"
    if 0xAC00 <= code_point <= 0xD7A3:
        return "LV" if (code_point - 0xAC00) % 28 == 0 else "LVT"
    return None


def _grapheme_property(character: str) -> str:
    code_point = ord(character)
    if code_point == 0x000D:
        return "CR"
    if code_point == 0x000A:
        return "LF"

    hangul = _hangul_grapheme_property(code_point)
    if hangul is not None:
        return hangul
    if 0x1F1E6 <= code_point <= 0x1F1FF:
        return "RI"
    if _in_ranges(code_point, _PREPEND_RANGES):
        return "Prepend"
    if code_point == 0x200D:
        return "ZWJ"

    category = unicodedata.category(character)
    if (
        category in {"Mn", "Me"}
        or code_point == 0x200C
        or 0x1F3FB <= code_point <= 0x1F3FF
        or 0xE0020 <= code_point <= 0xE007F
        or 0xFF9E <= code_point <= 0xFF9F
    ):
        return "Extend"
    if category == "Mc" or code_point in _SPACING_MARK_EXCEPTIONS:
        return "SpacingMark"
    if category in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
        return "Control"
    return "Other"


def _is_extended_pictographic(character: str) -> bool:
    code_point = ord(character)
    # Regional indicators share the main emoji block but are governed by
    # GB12/GB13 rather than Extended_Pictographic's GB11 rule.
    return not 0x1F1E6 <= code_point <= 0x1F1FF and _in_ranges(
        code_point, _EXTENDED_PICTOGRAPHIC_RANGES
    )


def _indic_script_range(code_point: int) -> tuple[int, int] | None:
    return next(
        (
            (start, end)
            for start, end in _INDIC_SCRIPT_RANGES
            if start <= code_point <= end
        ),
        None,
    )


def _is_indic_consonant(character: str) -> bool:
    return (
        _indic_script_range(ord(character)) is not None
        and unicodedata.category(character) == "Lo"
    )


def _is_indic_linker(character: str) -> bool:
    if _indic_script_range(ord(character)) is None:
        return False
    name = unicodedata.name(character, "")
    return "VIRAMA" in name or "HALANT" in name


def _matches_indic_conjunct_rule(
    text: str, properties: list[str], index: int
) -> bool:
    """Approximate GB9c using only standard-library Unicode metadata."""
    if not _is_indic_consonant(text[index]):
        return False

    script_range = _indic_script_range(ord(text[index]))
    lookbehind = index - 1
    saw_linker = False
    while lookbehind >= 0 and properties[lookbehind] in {"Extend", "ZWJ"}:
        character = text[lookbehind]
        if _indic_script_range(ord(character)) not in {None, script_range}:
            return False
        saw_linker = saw_linker or _is_indic_linker(character)
        lookbehind -= 1
    return (
        saw_linker
        and lookbehind >= 0
        and _indic_script_range(ord(text[lookbehind])) == script_range
        and _is_indic_consonant(text[lookbehind])
    )


def _has_grapheme_break(text: str, properties: list[str], index: int) -> bool:
    """Apply the ordered extended-grapheme rules at ``text[index]``."""
    previous = properties[index - 1]
    current = properties[index]

    # GB3 through GB5: CRLF is one cluster; all other controls form boundaries.
    if previous == "CR" and current == "LF":
        return False
    if previous in {"Control", "CR", "LF"}:
        return True
    if current in {"Control", "CR", "LF"}:
        return True

    # GB6 through GB8: conjoining Hangul jamo and syllables.
    if previous == "L" and current in {"L", "V", "LV", "LVT"}:
        return False
    if previous in {"LV", "V"} and current in {"V", "T"}:
        return False
    if previous in {"LVT", "T"} and current == "T":
        return False

    # GB9, GB9a, and GB9b: extending marks, spacing marks, and prepends.
    if current in {"Extend", "ZWJ", "SpacingMark"}:
        return False
    if previous == "Prepend":
        return False

    # GB9c: keep common Indic consonant/linker/consonant sequences together.
    if _matches_indic_conjunct_rule(text, properties, index):
        return False

    # GB11: Extended_Pictographic Extend* ZWJ × Extended_Pictographic.
    if previous == "ZWJ" and _is_extended_pictographic(text[index]):
        lookbehind = index - 2
        while lookbehind >= 0 and properties[lookbehind] == "Extend":
            lookbehind -= 1
        if lookbehind >= 0 and _is_extended_pictographic(text[lookbehind]):
            return False

    # GB12/GB13: pair regional indicators from the start of each RI run.
    if previous == "RI" and current == "RI":
        preceding_regional_indicators = 0
        lookbehind = index - 1
        while lookbehind >= 0 and properties[lookbehind] == "RI":
            preceding_regional_indicators += 1
            lookbehind -= 1
        if preceding_regional_indicators % 2 == 1:
            return False

    return True


def _grapheme_cluster_count(text: str) -> int:
    if not text:
        return 0
    properties = [_grapheme_property(character) for character in text]
    return 1 + sum(_has_grapheme_break(text, properties, index) for index in range(1, len(text)))


def _is_word_base(character: str) -> bool:
    category = unicodedata.category(character)
    return category[0] in {"L", "N"} or category == "Pc"


def _word_count(text: str) -> int:
    words = 0
    in_word = False
    for index, character in enumerate(text):
        category = unicodedata.category(character)
        if _is_word_base(character):
            if not in_word:
                words += 1
            in_word = True
        elif category[0] == "M" and in_word:
            continue
        elif (
            character in {"'", "\N{RIGHT SINGLE QUOTATION MARK}"}
            and in_word
            and index + 1 < len(text)
            and _is_word_base(text[index + 1])
        ):
            continue
        else:
            in_word = False
    return words


def count_text(text: str) -> dict[str, int]:
    """Return UTF-8, Unicode, grapheme, word, line, and JavaScript-unit counts.

    Words are runs of Unicode letters, numbers, marks, and connector punctuation;
    an ASCII apostrophe or U+2019 joins adjacent runs. JavaScript string units are
    UTF-16 code units. Extended grapheme clusters use a local implementation of
    the core UAX #29 rules, including combining, Hangul, and emoji sequences.
    """
    unicode_scalars = sum(_is_scalar(character) for character in text)
    return {
        "utf8_bytes": _utf8_length(text),
        "unicode_code_points": len(text),
        "unicode_scalars": unicode_scalars,
        "grapheme_clusters": _grapheme_cluster_count(text),
        "words": _word_count(text),
        "lines": _line_count(text),
        "javascript_string_units": sum(2 if ord(character) > 0xFFFF else 1 for character in text),
    }


def _reject_json_number(token: str) -> None:
    raise _NonStandardJSONNumber(token)


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if value is _JSON_NUMBER:
        return "number"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    # parse_int and parse_float always return _JSON_NUMBER, so reaching this
    # branch would indicate a programming error rather than user input.
    raise TypeError("unexpected JSON value type")


def _point(text: str, character_offset: int) -> dict[str, int]:
    """Build a zero-based character/byte and one-based line/column source point."""
    line = 1
    column = 1
    previous_was_carriage_return = False
    for character in text[:character_offset]:
        if character == "\r":
            line += 1
            column = 1
            previous_was_carriage_return = True
        elif character == "\n":
            if not previous_was_carriage_return:
                line += 1
            column = 1
            previous_was_carriage_return = False
        else:
            column += 1
            previous_was_carriage_return = False
    return {
        "line": line,
        "column": column,
        "character_offset": character_offset,
        "byte_offset": _utf8_length(text[:character_offset]),
    }


def _previous_non_whitespace(text: str, position: int) -> int | None:
    position -= 1
    while position >= 0 and text[position] in " \t\r\n":
        position -= 1
    return position if position >= 0 else None


def _json_diagnostic(text: str, error: json.JSONDecodeError) -> tuple[str, str]:
    """Translate implementation messages into stable, input-independent diagnostics."""
    position = error.pos
    previous = _previous_non_whitespace(text, position)
    current = text[position] if position < len(text) else None

    if error.msg.startswith("Illegal trailing comma"):
        return "trailing_comma", "Trailing commas are not permitted in JSON."
    if current in {"]", "}"} and previous is not None and text[previous] == ",":
        return "trailing_comma", "Trailing commas are not permitted in JSON."
    if position >= len(text):
        return "unexpected_end", "JSON input ended before a complete value was found."
    if text.startswith(("//", "/*"), position):
        return "comment_not_allowed", "Comments are not permitted in JSON."
    if current == "'" and error.msg in {
        "Expecting value",
        "Expecting property name enclosed in double quotes",
    }:
        return (
            "single_quoted_string",
            "JSON strings and object property names must use double quotes.",
        )
    if error.msg == "Expecting value":
        return "expected_value", "Expected a JSON value."
    if error.msg == "Expecting property name enclosed in double quotes":
        return "expected_property_name", "Expected an object property name in double quotes."
    if error.msg == "Expecting ':' delimiter":
        return "expected_colon", "Expected ':' after an object property name."
    if error.msg == "Expecting ',' delimiter":
        return "expected_comma_or_end", "Expected ',' or the end of the current array or object."
    if error.msg == "Extra data":
        return "extra_data", "Unexpected content follows the first JSON value."
    if error.msg.startswith("Unterminated string"):
        return "unterminated_string", "A JSON string is not terminated."
    if error.msg.startswith("Invalid \\u"):
        return "invalid_unicode_escape", "A JSON string contains an invalid Unicode escape."
    if error.msg.startswith("Invalid \\escape"):
        return "invalid_escape", "A JSON string contains an invalid escape sequence."
    if error.msg.startswith("Invalid control character"):
        return (
            "unescaped_control_character",
            "A JSON string contains an unescaped control character.",
        )
    if error.msg.startswith("Unexpected UTF-8 BOM"):
        return "unexpected_bom", "A Unicode byte-order mark is not permitted here."
    return "invalid_syntax", "The input is not valid JSON."


def _json_diagnostic_position(text: str, error: json.JSONDecodeError, code: str) -> int:
    """Normalize decoder locations that differ across supported Python releases."""
    if code != "trailing_comma":
        return error.pos
    if error.pos < len(text) and text[error.pos] == ",":
        return error.pos
    previous = _previous_non_whitespace(text, error.pos)
    if previous is not None and text[previous] == ",":
        return previous
    return error.pos


def _find_unquoted_token(text: str, token: str) -> int:
    """Locate a decoder-recognized constant without matching text inside strings."""
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            index += 1
            continue
        if text.startswith(token, index):
            return index
        index += 1
    return 0


def _excessive_json_nesting_position(text: str) -> int | None:
    """Return the opener that exceeds the bounded parser depth, if present."""
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _JSON_NESTING_LIMIT:
                return index
        elif character in "]}" and depth:
            depth -= 1
    return None


def validate_json(text: str) -> dict[str, Any]:
    """Validate JSON with a parser and return stable point diagnostics on failure.

    This function never evaluates the submitted text as code. Python's permissive
    NaN and infinity extensions are explicitly rejected. Error character and byte
    offsets are zero-based; line and column are one-based.
    """
    excessive_nesting = _excessive_json_nesting_position(text)
    if excessive_nesting is not None:
        return {
            "valid": False,
            "error": {
                "code": "nesting_too_deep",
                "message": f"JSON nesting exceeds the {_JSON_NESTING_LIMIT}-level limit.",
                **_point(text, excessive_nesting),
            },
        }

    try:
        value = json.loads(
            text,
            parse_constant=_reject_json_number,
            parse_float=lambda _: _JSON_NUMBER,
            parse_int=lambda _: _JSON_NUMBER,
        )
    except _NonStandardJSONNumber as error:
        position = _find_unquoted_token(text, error.token)
        return {
            "valid": False,
            "error": {
                "code": "non_standard_number",
                "message": "JSON numbers cannot be NaN or infinity.",
                **_point(text, position),
            },
        }
    except json.JSONDecodeError as error:
        code, message = _json_diagnostic(text, error)
        position = _json_diagnostic_position(text, error, code)
        return {
            "valid": False,
            "error": {
                "code": code,
                "message": message,
                **_point(text, position),
            },
        }
    except RecursionError:
        # This is a final guard for unusual decoder/runtime recursion limits.
        return {
            "valid": False,
            "error": {
                "code": "nesting_too_deep",
                "message": "JSON nesting exceeds this runtime's parser limit.",
                **_point(text, 0),
            },
        }
    return {"valid": True, "value_type": _json_type(value)}


def _unicode_name(character: str, category: str) -> str:
    name = unicodedata.name(character, "")
    if name:
        return name
    code_point = ord(character)
    if code_point in _CONTROL_NAMES:
        return _CONTROL_NAMES[code_point]
    if category == "Cc":
        return "CONTROL"
    if category == "Co":
        return "PRIVATE USE"
    if category == "Cs":
        return "SURROGATE"
    return "UNASSIGNED"


def _visible_representation(character: str, category: str) -> str:
    code_point = ord(character)
    if category[0] in {"C", "Z"} or (
        0xFE00 <= code_point <= 0xFE0F or 0xE0100 <= code_point <= 0xE01EF
    ):
        return escape_code_point(code_point)
    if category[0] == "M":
        return "\N{DOTTED CIRCLE}" + character
    return character


def inspect_code_points(text: str) -> dict[str, Any]:
    """Return bounded Unicode metadata and source positions for each code point."""
    total = len(text)
    returned = min(total, DETAIL_LIMIT)
    characters: list[dict[str, Any]] = []
    byte_index = 0
    javascript_unit_index = 0
    line = 1
    column = 1
    previous_was_carriage_return = False

    for index, character in enumerate(text[:returned]):
        code_point = ord(character)
        category = unicodedata.category(character)
        utf8_bytes = _utf8_values(character)
        javascript_units = 2 if code_point > 0xFFFF else 1
        characters.append(
            {
                "index": index,
                "code_point": format_code_point(code_point),
                "decimal": code_point,
                "name": _unicode_name(character, category),
                "category": category,
                "utf8_bytes": utf8_bytes,
                "utf8_hex": " ".join(f"{byte:02X}" for byte in utf8_bytes),
                "position": {
                    "byte_start": byte_index,
                    "byte_end": byte_index + len(utf8_bytes),
                    "code_point_start": index,
                    "code_point_end": index + 1,
                    "javascript_unit_start": javascript_unit_index,
                    "javascript_unit_end": javascript_unit_index + javascript_units,
                    "line": line,
                    "column": column,
                },
                "visible": _visible_representation(character, category),
            }
        )

        byte_index += len(utf8_bytes)
        javascript_unit_index += javascript_units
        if character == "\r":
            line += 1
            column = 1
            previous_was_carriage_return = True
        elif character == "\n":
            if not previous_was_carriage_return:
                line += 1
            column = 1
            previous_was_carriage_return = False
        else:
            column += 1
            previous_was_carriage_return = False

    return {
        "summary": {
            "total": total,
            "returned": returned,
            "truncated": total > DETAIL_LIMIT,
        },
        "characters": characters,
    }
