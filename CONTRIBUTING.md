# Contributing

Contributions should keep the API deterministic, bounded, privacy-preserving,
and compatible with the committed OpenAPI contract.

## Development workflow

1. Create a focused branch.
2. Install with `pip install -e ".[dev]"`. If the development extras are not
   available, use `pip install -r requirements.txt` followed by
   `pip install pytest httpx ruff`.
3. Add or update tests for behavior changes.
4. Run `ruff check .` and `pytest`.
5. Update `docs/API.md` when the public contract changes, then run
   `python -m scripts.generate_openapi` and commit the generated
   `app/static/openapi.json`.

Do not commit credentials, submitted user content, generated browser profiles,
or unreviewed third-party assets. Changes to vendored Swagger UI files must
update the pinned package version, hashes, license record, and tests together.
