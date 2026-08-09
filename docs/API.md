# UTF-8 and Unicode analysis API

Status: implementation complete; production deployment requires the
`API_RATE_LIMIT_HMAC_KEY` secret

Last reviewed: 2026-08-09

The public v1 API provides strict, bounded analysis of UTF-8, Unicode text, and
JSON. It does not modify submitted content, fetch URLs, accept files or archives,
persist results, or provide an availability service-level agreement.

The application routes and static assets are defined in `app/main.py`. Analysis
algorithms live in `app/engine.py`, `app/unicode_review.py`, and
`app/text_tools.py`. They use the Python standard library and make no remote
lookups. The in-memory limiter is defined in `app/rate_limit.py`.

## Swagger UI and OpenAPI

The API origin serves a reviewed, self-contained Swagger UI:

- Swagger UI: `/` with `/docs` redirecting to it
- OpenAPI 3.1 document: `/openapi.json`

The page does not load a CDN, analytics script, or remote schema validator. It
calls an analysis endpoint only when a visitor uses Swagger UI’s **Execute**
control. The static document is generated reproducibly with:

```bash
python -m scripts.generate_openapi
```

Tests ensure the generated document matches the committed artifact, implemented
paths, declared schemas, examples, and live example responses.

## Endpoints

| Method and path | Result |
| --- | --- |
| `GET /v1/health` | Deployment and data-version identifiers. |
| `POST /v1/hidden-characters` | Hidden, formatting, bidirectional, whitespace, and control findings. |
| `POST /v1/mojibake` | Likely legacy-decoding artifacts and replacement characters. |
| `POST /v1/normalization` | NFC, NFD, NFKC, and NFKD comparisons. |
| `POST /v1/mixed-script-confusables` | Writing-system summary and review findings. |
| `POST /v1/text-counts` | UTF-8, Unicode, word, line, and JavaScript counts. |
| `POST /v1/json-validation` | JSON validity, top-level type, or stable error location. |
| `POST /v1/code-points` | Complete character-by-character inspection for bounded input. |

Query parameters are rejected on every endpoint.

## Shared analysis request

Every `POST` endpoint accepts exactly one `input` object. Unknown properties are
rejected at every level.

### Unicode text

```json
{
  "input": {
    "kind": "text",
    "value": "café"
  }
}
```

The outer JSON envelope is decoded strictly as UTF-8, except that one leading
UTF-8 BOM is accepted and removed. The parsed string must contain Unicode scalar
values; unpaired surrogate code points are rejected. Response byte coordinates
refer to the string’s UTF-8 encoding because the service cannot recover bytes a
caller decoded before creating JSON.

### Original bytes

```json
{
  "input": {
    "kind": "bytes",
    "base64": "Y2Fmw6k=",
    "declared_charset": "utf-8"
  }
}
```

`base64` must use the standard alphabet, canonical padding, and no whitespace.
`declared_charset` is required and must be exactly `utf-8`. Response byte
coordinates refer to the decoded submitted bytes.

Original bytes do not have to be valid UTF-8. Invalid UTF-8 is an HTTP `200`
domain result that reports the first invalid byte and skips the requested check;
the decoder does not substitute U+FFFD and continue.

### Hidden-character profiles

Only `POST /v1/hidden-characters` accepts an optional top-level `profile`:

```json
{
  "input": {
    "kind": "text",
    "value": "hello\u200Bworld"
  },
  "profile": "identifier"
}
```

| Profile | Behavior |
| --- | --- |
| `general` | Default severities for ordinary text. |
| `identifier` | Raises selected joining, bidi, formatting, variation-selector, tag, and no-break-space findings. |

Profiles affect severity, not validity. Every other analysis endpoint rejects a
`profile` property.

## Shared limits and HTTP behavior

| Limit | Enforced value |
| --- | ---: |
| JSON request envelope | 256 KiB |
| UTF-8 encoding of text input | 32 KiB |
| Decoded original-byte input | 32 KiB |
| Detailed hidden, mojibake, or script findings | 500 |
| Characters in each normalization changed-range detail | 500 |
| Code points accepted by `/v1/code-points` | 500 |
| JSON container nesting handled by `/v1/json-validation` | 512 levels |
| Application rate limit | 60 attempts per 60 seconds per anonymous actor and process |

The server enforces actual body size even without `Content-Length`. A malformed
or dishonest `Content-Length` does not bypass limits. Any `Content-Encoding`
header is rejected, including `identity`. `Content-Type` must be
`application/json`, optionally with a UTF-8 charset parameter.

The limiter runs after cheap path, query, method, media-type, encoding, and
declared-size checks, but before the body is fully read and parsed. Malformed
JSON, invalid Base64, and invalid original bytes therefore consume an attempt.
CORS preflight and health checks do not consume this quota.

The limiter uses an HMAC-derived identity based on the request source address.
Raw addresses, the HMAC secret, and derived keys are not returned or logged by
application code. State is per-process, in memory, and reset on restart. Shared
networks and privacy relays can group unrelated callers; multiple replicas do
not share the quota.

## Shared response fields

Completed tool responses include:

```json
{
  "request_id": "req_0123456789abcdef0123456789abcdef",
  "status": "complete",
  "engine_version": "0.2.0",
  "unicode_version": "16.0.0",
  "input": {
    "kind": "text",
    "bytes": 4,
    "utf16_code_units": 4,
    "unicode_scalars": 4,
    "lines": 1,
    "offset_basis": "utf8-encoding-of-input-string"
  },
  "encoding": {
    "valid_utf8": true,
    "basis": "strict-request-envelope-and-reencoded-text"
  }
}
```

`unicode_version` is the Unicode database version supplied by the running
Python interpreter, so the value can differ across supported Python versions.
Record it when reproducibility matters. Hidden-character responses additionally
include `ruleset_version` and `profile` after successful decoding.

Offsets are zero-based and half-open. Lines and columns are one-based Unicode
scalar coordinates. CR, LF, and CRLF are treated as line endings, with CRLF
counted once. Endpoint-specific responses state whether offsets are UTF-8 bytes,
Unicode scalar/code-point indices, or UTF-16 JavaScript string units.

Implemented statuses are:

| Endpoint | Completion statuses |
| --- | --- |
| Hidden characters, mojibake, mixed-script review | `clean`, `issues_found` |
| Normalization | `normalized`, `changes_found` |
| Text counts and code-point inspector | `complete` |
| JSON validator | `valid_json`, `invalid_json` |
| Every analysis endpoint with invalid original bytes | `invalid_utf8` |

## `GET /v1/health`

Returns deployment and analysis metadata without using the analysis quota:

```json
{
  "status": "ok",
  "deployment": "api-v1",
  "engine_version": "0.2.0",
  "ruleset_version": "hidden-2026-08-08",
  "unicode_version": "16.0.0"
}
```

The Unicode version shown is illustrative; the actual response reports the
running interpreter’s database version. Only `GET` is supported.

## `POST /v1/hidden-characters`

Reports invisible, joining, formatting, bidirectional, and control characters
without changing or echoing the full input.

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"input":{"kind":"text","value":"hello\u200Bworld"},"profile":"general"}' \
  http://127.0.0.1:8080/v1/hidden-characters
```

A finding contains a stable rule, category, severity, title, exact byte/UTF-16/
scalar/line/column location, escaped observation, code point, UTF-8 bytes, and
explanation:

```json
{
  "id": "f_1",
  "rule": "hidden.zero_width_space",
  "category": "hidden_text",
  "severity": "warning",
  "title": "Zero-width space",
  "location": {
    "byte_start": 5,
    "byte_end": 8,
    "utf16_start": 5,
    "utf16_end": 6,
    "scalar_start": 5,
    "scalar_end": 6,
    "line": 1,
    "column": 6
  },
  "observed": {
    "escaped": "\\u200B",
    "code_points": ["U+200B"],
    "utf8_hex": "E2 80 8B"
  },
  "explanation": "This character has no visible width and can separate otherwise adjacent text."
}
```

The current `hidden-2026-08-08` ruleset covers:

| Group | Examples |
| --- | --- |
| Hidden spaces and joining | U+200B, U+200C, U+200D, U+2060, U+FEFF |
| Formatting | U+00AD, U+034F, U+2061–U+2064, selected Hangul fillers |
| Bidirectional controls | U+061C, U+200E–U+200F, U+202A–U+202E, U+2066–U+206F |
| Variation selectors | U+FE00–U+FE0F, U+E0100–U+E01EF |
| Tag characters | U+E0000–U+E007F |
| Controls | C0 and C1 except tab, LF, and CR |
| No-break space | U+00A0 |

Valid joining and formatting characters are contextual, not automatically
malicious. The engine does not treat text as suspicious merely because it is
non-ASCII. It scans the complete bounded input even if only 500 findings are
returned; `summary.total` retains the full count and `summary.truncated` reports
omitted details.

## `POST /v1/mojibake`

Flags two patterns:

- U+FFFD REPLACEMENT CHARACTER, which often marks an earlier failed decode.
- A complete 2-, 3-, or 4-byte UTF-8 sequence whose bytes are currently
  displayed as Latin-1 or Windows-1252 characters.

For example, `cafÃ©` produces an `issues_found` result with rule
`mojibake.utf8_bytes_as_legacy_text`. The finding covers `Ã©`, reports the
interpreted bytes `C3 A9`, and identifies U+00E9 as the possible intended
character.

This is a conservative heuristic. Genuine text can contain the same character
sequence, and many encoding failures cannot be inferred from rendered Unicode.
The endpoint does not repair text and a finding is never proof of corruption.

## `POST /v1/normalization`

Compares the submitted scalar sequence independently with NFC, NFD, NFKC, and
NFKD:

```json
{
  "input": {
    "kind": "text",
    "value": "e\u0301"
  }
}
```

The response reports `is_normalized` and output metrics for every form. Multiple
forms can match simultaneously; the example above matches NFD and NFKD but not
NFC or NFKC. Each differing form produces a finding over the smallest shared-
prefix/shared-suffix envelope containing all changes.

The response does not return the complete input or normalized string. It does
return bounded source and normalized character details for each changed range,
including escaped code points, UTF-8 bytes, names, categories, scripts, and
positions. Compatibility normalization can change distinctions important to an
application; the endpoint reports differences and does not prescribe a form.

## `POST /v1/mixed-script-confusables`

Summarizes scripts used by letters, selects a dominant script by count and first
appearance, and recommends review for unexpected mixtures. `Common`,
`Inherited`, and unknown characters do not independently create a mixed-script
condition. Familiar Han/Hiragana/Katakana, Han/Bopomofo, and Han/Hangul
combinations are summarized but not automatically flagged.

In Latin text, a versioned curated subset of Greek and Cyrillic characters that
resemble ASCII letters is reported. For `pаypal`, where the second character is
Cyrillic U+0430, the result includes:

```json
{
  "status": "issues_found",
  "confusable_data": {
    "kind": "curated_subset",
    "version": "curated-greek-cyrillic-to-ascii-2026-08-09",
    "source_scripts": ["Cyrillic", "Greek"],
    "target_script": "ASCII Latin",
    "uts39_complete": false
  },
  "scripts": [
    {"script": "Latin", "count": 5, "first_scalar": 0},
    {"script": "Cyrillic", "count": 1, "first_scalar": 1}
  ],
  "dominant_script": "Latin",
  "is_mixed_script": true,
  "expected_script_combination": false,
  "review_recommended": true
}
```

Script classification is conservatively derived from standard-library Unicode
names because Python does not expose Script properties. Confusable coverage is
not complete UTS #39 data. Use this endpoint as a human-review aid for names,
links, and identifiers, not as an authentication or authorization decision.

## `POST /v1/text-counts`

Returns:

```json
{
  "counts": {
    "utf8_bytes": 28,
    "unicode_code_points": 16,
    "unicode_scalars": 16,
    "grapheme_clusters": 11,
    "words": 2,
    "lines": 2,
    "javascript_string_units": 19
  }
}
```

The example input is `Cafe\u0301 👩🏽‍💻\r\nflag`.

Count definitions:

- UTF-8 bytes are the length of strict UTF-8 encoding.
- Code points are Python string elements. Because request validation rejects
  surrogates, code-point and scalar counts are equal for API input.
- Graphemes use a local extended-grapheme implementation covering controls and
  CRLF, Hangul composition, combining and spacing marks, prepends, common Indic
  linker conjuncts, emoji ZWJ sequences, modifiers/tags, and regional-indicator
  pairing. Extended-pictographic and Indic properties are conservative local
  approximations because the standard library does not expose them; this is not
  a formal Unicode segmentation conformance claim.
- Words are runs of Unicode letters, numbers, marks, and connector punctuation.
  ASCII apostrophe and U+2019 join adjacent runs.
- Empty text occupies one line. Each CR, LF, or CRLF ending starts one additional
  line, with CRLF counted once.
- JavaScript string units are UTF-16 code units, so a non-BMP scalar counts as
  two units.

## `POST /v1/json-validation`

The `input.value` string is treated as JSON data, never evaluated as code. A
valid result returns its top-level type:

```json
{
  "status": "valid_json",
  "valid": true,
  "value_type": "object"
}
```

Objects, arrays, strings, numbers, booleans, and null are all accepted as
top-level values. Duplicate object names are syntactically accepted; the
endpoint validates JSON syntax and does not enforce an application schema or
duplicate-name policy. NaN, Infinity, and -Infinity are rejected as nonstandard.
A leading BOM inside the submitted inner JSON is rejected. Processing is bounded
at 512 nested arrays/objects.

Invalid inner JSON remains an HTTP `200` analysis result:

```json
{
  "status": "invalid_json",
  "valid": false,
  "error": {
    "code": "expected_value",
    "message": "Expected a JSON value.",
    "line": 1,
    "column": 10,
    "character_offset": 9,
    "byte_offset": 9
  }
}
```

Character and byte offsets are zero-based; line and column are one-based.
Diagnostics use stable API codes rather than returning Python exception text or
input excerpts. Malformed outer API JSON is different: it receives HTTP `400`
`invalid_request` before the inner validator runs.

## `POST /v1/code-points`

Lists every character for input of at most 500 code points. Larger input receives
HTTP `413`; accepted results are complete and never silently truncated.

For `A😀`, the emoji item is:

```json
{
  "index": 1,
  "code_point": "U+1F600",
  "decimal": 128512,
  "name": "GRINNING FACE",
  "category": "So",
  "utf8_bytes": [240, 159, 152, 128],
  "utf8_hex": "F0 9F 98 80",
  "position": {
    "byte_start": 1,
    "byte_end": 5,
    "code_point_start": 1,
    "code_point_end": 2,
    "javascript_unit_start": 1,
    "javascript_unit_end": 3,
    "line": 1,
    "column": 2
  },
  "visible": "😀"
}
```

Printable characters are returned directly in `visible`. Combining marks use a
dotted-circle form. Controls, separators, format characters, and variation
selectors use escaped representations. Names and categories come from the
running Python Unicode database.

## Invalid original UTF-8

Canonical Base64 `/w==` represents one invalid byte. Every analysis endpoint
returns HTTP `200` with the same core shape:

```json
{
  "request_id": "req_0123456789abcdef0123456789abcdef",
  "status": "invalid_utf8",
  "engine_version": "0.2.0",
  "unicode_version": "16.0.0",
  "input": {
    "kind": "bytes",
    "bytes": 1,
    "offset_basis": "submitted-bytes"
  },
  "encoding": {
    "valid_utf8": false,
    "basis": "submitted-bytes",
    "first_invalid_byte": 0
  },
  "skipped": [
    {"check": "text-counts", "reason": "invalid_utf8"}
  ]
}
```

The skipped check matches the requested endpoint. The hidden-character variant
also includes `ruleset_version`, an empty summary, and an empty findings list.

## Errors

Transport, envelope, quota, and server errors use a stable envelope:

```json
{
  "error": {
    "code": "input_too_large",
    "message": "The request or decoded input exceeds its size limit.",
    "request_id": "req_0123456789abcdef0123456789abcdef"
  }
}
```

| HTTP status | Error codes and behavior |
| ---: | --- |
| `400` | `invalid_request`, `invalid_envelope_utf8`, `invalid_base64`, or `unsupported_profile` on the hidden endpoint. |
| `404` | Unknown paths use the sanitized `invalid_request` envelope. |
| `405` | Unsupported method, with an `Allow` header. |
| `413` | `input_too_large` for an oversized envelope, decoded input, or inspector input. |
| `415` | `unsupported_media_type` or `unsupported_content_encoding`. |
| `429` | `rate_limited`, with `Retry-After: 60`. |
| `500` | Sanitized `internal_error`. |
| `503` | `limiter_unavailable`; analysis fails closed if identity or limiter setup is unavailable. |

All application JSON responses are UTF-8, compact, and newline-terminated. They
include `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and an
opaque `X-Request-ID`. Parser exception text, stack traces, input excerpts, raw
bytes, and limiter keys are not returned. A reverse proxy may reject a request
before application code runs, in which case its response need not use this
envelope.

## CORS

Server-to-server clients do not need CORS. Browser analysis requests are allowed
only from `https://utf8.ai` and `https://www.utf8.ai`. Preflight permits `POST`
with `Content-Type` only, returns a ten-minute maximum age, and does not allow
credentials or wildcard origins. Invalid preflight receives `400`.

## Privacy and client guidance

Application code does not write request bodies, decoded text, byte sequences,
findings, filenames, or response content to logs or storage. It has no content
database, queue, built-in analytics integration, or third-party request path.
Hosting-platform access logs and retention are deployment controls and must be
reviewed before public use.

Analysis necessarily requires sending content to the deployed API. Use a local
deployment when content must not leave a machine. The hidden endpoint avoids a
raw character field; mojibake, normalization, and script review return bounded
source-derived details; the inspector explicitly returns printable characters.

Clients should branch on `status`, preserve each response’s coordinate basis,
and never treat a heuristic finding as proof of malicious or corrupted content.
Rule, confusable-data, Python, or Unicode updates can change results while the
URL major version remains v1. Record `engine_version`, `ruleset_version`,
`unicode_version`, and confusable-data version when reproducibility matters.
