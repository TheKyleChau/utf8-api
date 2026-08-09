# Third-party licenses

License audit performed: 2026-08-09

For every Python package below, see `requirements.txt` / `pyproject.toml` for
the exact pinned version. Versions are intentionally not duplicated here so
the dependency declarations remain authoritative.

## Python runtime dependencies

| Package | License identifier | Version reference |
| --- | --- | --- |
| `fastapi` | MIT | See `requirements.txt` / `pyproject.toml` |
| `starlette` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `uvicorn` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `pydantic` | MIT | See `requirements.txt` / `pyproject.toml` |
| `pydantic-core` | MIT | See `requirements.txt` / `pyproject.toml` |

### Uvicorn dependencies and standard extras

| Package | License identifier | Version reference |
| --- | --- | --- |
| `click` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `h11` | MIT | See `requirements.txt` / `pyproject.toml` |
| `httptools` | MIT | See `requirements.txt` / `pyproject.toml` |
| `PyYAML` | MIT | See `requirements.txt` / `pyproject.toml` |
| `uvloop` | MIT | See `requirements.txt` / `pyproject.toml` |
| `watchfiles` | MIT | See `requirements.txt` / `pyproject.toml` |
| `websockets` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `python-dotenv` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `colorama` (Windows only) | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |

## Python development dependencies

| Package | License identifier | Version reference |
| --- | --- | --- |
| `pytest` | MIT | See `requirements.txt` / `pyproject.toml` |
| `httpx` | BSD-3-Clause | See `requirements.txt` / `pyproject.toml` |
| `ruff` | MIT | See `requirements.txt` / `pyproject.toml` |

## Vendored documentation assets

| Package | License identifier | Relationship |
| --- | --- | --- |
| `swagger-ui-dist` | Apache-2.0 | Vendored Swagger UI distribution |
| `@scarf/scarf` | Apache-2.0 | Transitive dependency recorded with the vendored bundle |

See [NOTICE](NOTICE) for the Swagger UI attribution distributed with this
project.

All listed dependencies use permissive MIT, BSD, or Apache-2.0 licenses; none
uses a copyleft GPL, AGPL, or LGPL license. These licenses are compatible with
this project's Apache-2.0 license.
