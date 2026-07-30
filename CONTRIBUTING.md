# Contributing to arch-kernel

## Environment

Install `uv`, select any supported Python version from 3.12 through 3.13, then
create the locked development environment:

```bash
uv sync --all-groups
```

The lockfile must remain synchronized with `pyproject.toml`.

## Quality Gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest -p no:cacheprovider
uv run python scripts/check_release.py
```

Use `uv run pytest -m property` for property tests and `uv run pytest -m
regression` for compatibility snapshots. To reproduce a Hypothesis failure,
rerun the emitted reproduction blob with `@reproduce_failure` or pass the
reported seed using `--hypothesis-seed`.

## Generated Contracts

Schemas are published only from the explicit built-in contract registry.
Regenerate fixture and regression evidence with:

```bash
uv run python scripts/build_fixture_manifest.py
uv run python scripts/build_regression_snapshots.py
uv run python scripts/build_release_manifest.py
```

Generated schemas, fixture manifests, and snapshots must change only with an
intentional contract change. Never weaken an invariant, delete a fixture, or
rewrite a snapshot solely to make a test pass.

## Versions and Migrations

`src/arch_kernel/__about__.py` is the single static version source. Update it
only with a matching changelog release heading. Contract versions are separate
semantic identities: schema-breaking changes require a documented compatible
version change and, where persisted payloads are affected, an explicit,
registered migration. No implicit migration or repair is allowed.

## Release Checks

`uv run python scripts/check_release.py` is fail closed and never publishes.
It validates generated evidence, builds and inspects distributions, installs
the wheel in isolation, verifies reproducibility, and applies dependency,
license, and release-governance policy.
