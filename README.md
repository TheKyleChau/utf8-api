# utf8-api

`utf8-api` is an open-source FastAPI service for bounded UTF-8, Unicode, text,
and JSON analysis. It accepts strict Unicode text or original bytes and exposes
seven analysis tools:

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/hidden-characters` | Locate invisible, formatting, bidirectional, whitespace, and control characters. |
| `POST /v1/mojibake` | Flag likely UTF-8 bytes displayed through Latin-1 or Windows-1252, plus U+FFFD. |
| `POST /v1/normalization` | Compare text with NFC, NFD, NFKC, and NFKD. |
| `POST /v1/mixed-script-confusables` | Review writing-system mixtures and a curated set of cross-script lookalikes. |
| `POST /v1/text-counts` | Count UTF-8 bytes, code points, graphemes, words, lines, and JavaScript string units. |
| `POST /v1/json-validation` | Validate JSON syntax and return stable error locations. |
| `POST /v1/code-points` | Inspect every accepted character’s Unicode metadata, UTF-8 bytes, and position. |

The analyzers use the Python standard library. Grapheme segmentation, script
review, and confusable matching are local conservative implementations with
documented limits; no third-party Unicode package or network lookup is used.

The repository includes the application, tests, an OpenAPI 3.1 contract, and a
self-hosted Swagger UI. Application code does not persist submitted content or
forward it to third parties. Most analyzers return only metrics and bounded
diagnostic details; the code-point inspector intentionally returns a visible or
escaped representation for each accepted character.

See [docs/API.md](docs/API.md) for the complete request, response, error,
privacy, algorithm, and rate-limit contract.

## Quick start

Send text in the strict request envelope:

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"input":{"kind":"text","value":"pаypal"}}' \
  http://127.0.0.1:8080/v1/mixed-script-confusables
```

The hidden-character endpoint alone accepts an optional `profile` of `general`
or `identifier`. Every other analyzer rejects `profile` and unknown fields.
Original bytes can be supplied as canonical standard Base64 with
`"declared_charset":"utf-8"`; invalid original UTF-8 is returned as a `200`
analysis result with the first invalid byte offset.

## Local development

Python 3.11 or later is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python run.py
```

The app serves Swagger UI and the API at <http://127.0.0.1:8080/> by default.
Set `HOST` or `PORT` to change the bind address or port.

Run checks with:

```bash
pytest
ruff check .
python -m scripts.generate_openapi
git diff --exit-code app/static/openapi.json
```

The last two commands regenerate the committed static OpenAPI document and
confirm that it was already current.

To use Docker Compose:

```bash
docker compose up --build
```

The Compose service is available at <http://localhost:8080/>. Local mode uses a
development-only anonymous limiter identity.

## Repository boundary

`pyproject.toml`, `requirements.txt`, `Dockerfile`, and `docker-compose.yml` are
committed so the application can be built and run reproducibly. They are not
public web assets and contain no secrets. The app serves only reviewed files
from `app/static/`; repository configuration is not downloadable from the API.

## Deployment configuration

Before running outside local development, set `API_RATE_LIMIT_HMAC_KEY` to a
random string of at least 32 characters. Use a `.env` file with Docker Compose,
or a real environment variable with `python run.py`. Never commit the key.

The built-in limiter is in-memory and per-process. Its state is not shared
across replicas and resets on restart. Multi-instance deployments need external
rate limiting. TLS and reverse-proxy termination are also the operator’s
responsibility; the application process serves plain HTTP.

## Security

Requests are strictly bounded, decoded, and validated. The service rejects
unknown fields, unsupported encodings, noncanonical Base64, oversized input,
and unsupported methods. Rate-limit identifiers are HMAC-derived and do not
expose source addresses. GitHub Actions runs tests, lint checks, and CodeQL
Advanced analysis for pull requests.

Please use GitHub private vulnerability reporting for security issues. See
[SECURITY.md](SECURITY.md).

## License and notices

The project source is licensed under Apache-2.0. Swagger UI is vendored from
`swagger-ui-dist@5.32.11` under Apache-2.0; its upstream license, notice, and
bundle dependency-license sidecar remain in `app/static/`. The project notice
records Copyright 2026 UTF8.ai contributors in [NOTICE](NOTICE). See
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the consolidated
dependency license record.
