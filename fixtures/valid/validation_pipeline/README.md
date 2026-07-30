# Validation pipeline fixtures

`cases.json` is the canonical K08 scenario catalog. Paths are relative to
`fixtures/` and intentionally reuse K03-K07 payloads instead of copying domain
contracts into orchestration fixtures.

Valid scenarios cover typed and raw state input, equivalent dual input, patch
projection, transition projection, release validation, and historical
validation. The matching invalid catalog contains fail-closed request,
registry, projection, precondition, and invariant-selection cases.
