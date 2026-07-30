# State patch fixtures

All WP-K05 patch fixtures use `fixtures/valid/minimal_project_state.json` as
their base aggregate. Its record version is `1` and its content fingerprint is
`sha256:37af488676c7b9f696e6c391e447b3da61b8074417778408080bfc6faa2feaaa`.

Files under `fixtures/invalid/state_patch` either fail `StatePatch` parsing or
produce the documented validation/dry-run failure against that same base state.
