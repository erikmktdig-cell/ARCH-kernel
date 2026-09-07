# Release Checklist

1. Confirm `src/arch_kernel/__about__.py` and the changelog release heading use
   the same PEP 440 version.
2. Confirm the private security reporting placeholder in `SECURITY.md` has
   been replaced with an authorized real channel.
3. Run `uv sync --all-groups` and `uv lock --check`.
4. Regenerate schemas, fixture manifests, regression snapshots, and
   `release/manifest.json`; review every diff.
5. Run the connected vulnerability gate with
   `ARCH_KERNEL_NETWORK_AUDIT=1 uv run python scripts/check_release.py`
   (set the environment variable using the syntax required by the current
   shell).
6. Review `dist/release-evidence.json` and `dist/dependency-licenses.json`.
7. Confirm the wheel and sdist hashes independently.
8. For a tag candidate, run
   `uv run python scripts/check_release.py --tag v<version>`.
9. After hosted CI and repository governance pass on the exact final commit,
   generate the C04 publication manifest with
   `uv run python scripts/build_publication_manifest.py --source-commit <sha>
   --test-count <passed> --skip-count <skipped> --coverage <percent>
   --hosted-ci-url <url>`.
10. Hash and attach the wheel, sdist, and generated publication manifest to the
    matching immutable GitHub Release. Publication to PyPI remains outside this
    repository's release workflow.

Runtime dependency licenses are a strict blocking gate. The development
environment is inventoried separately in `dist/dependency-licenses.json`;
unknown or mixed metadata there is reported for manual review and does not
change the runtime distribution license result. The inventory is metadata
inspection, not a legal conclusion.

Builds use the static version in `src/arch_kernel/__about__.py` and
`SOURCE_DATE_EPOCH=1784678400`. The stable release manifest contains no
timestamps or machine-dependent artifact hashes; candidate evidence is written
under ignored `dist/`.
