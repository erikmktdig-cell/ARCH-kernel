# Fixture Catalog

`manifest.json` is the canonical WP-K11 index for every JSON fixture below
this directory. Entries are ordered by stable lowercase dotted key and bind
each relative POSIX path to its work-package owner, fixture class, expected
outcome, and canonical payload fingerprint.

Regenerate intentionally after changing fixture content:

```powershell
uv run python scripts/build_fixture_manifest.py
```

Normal tests never rewrite fixtures or snapshots. `tests.fixture_catalog`
loads UTF-8 data, normalizes line endings, validates manifest consistency, and
returns detached structures.
