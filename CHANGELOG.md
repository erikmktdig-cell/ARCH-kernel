# Changelog

All notable changes to this project will be documented in this file.

This project follows a simplified Keep a Changelog format.

## [Unreleased]

## [0.2.0] - 2026-09-07

### Added

- C04-K release closeout evidence with installed-distribution workflow,
  ProjectState 2.0.0 migration and legacy phase compatibility checks, plus a
  deterministic final publication manifest tied to the release commit and CI.
- C01 generic `WorkflowId`, validated workflow namespaces and state tokens,
  immutable closed `WorkflowDefinition`, authoritative versioned
  `WorkflowStateRecord`, and deterministic `WorkflowDefinitionRegistry`.
- Generic `workflow_state` transitions bound to exact definition versions and
  fingerprints, with fail-closed state validation, mandatory optimistic
  preconditions, and mutation confined to the targeted workflow record.
- ProjectState 2.0.0 workflow registry plus an explicit K10 migration from
  ProjectState 1.0.0 that creates no inferred workflows.
- Unit, property, migration, regression, and architecture coverage proving
  deterministic lookup, deep definition immutability, scope confinement, and
  the absence of downstream vocabulary or dependencies.

### Changed

- The built-in public contract catalog now contains 38 contracts. Existing
  `PhaseCode`, `PhaseStatus`, and legacy transition-domain values remain
  byte-identical; workflow state is explicitly distinct from phase status.

## [0.1.0] - 2026-07-28

### Added

- WP-K12 deterministic release manifest and candidate evidence, direct wheel
  and sdist inspection, isolated installed-package smoke testing, clean-copy
  reproducible builds, dependency and license policy checks, fail-closed
  release orchestration, least-privilege CI/release workflows, Dependabot
  policy, security policy, contribution guide, and human release checklist.
- WP-K11 canonical fixture manifest, detached test-only loader, deterministic
  fixture generation, fixture classes, ownership metadata, payload
  fingerprints, and test-time coverage matrix.
- Bounded reusable Hypothesis strategies for IDs, strict JSON, project state,
  events, patches, transitions, invariants, validation, registries, and
  migrations, with local, CI, and debug profiles.
- Cross-kernel determinism, immutability, round-trip, metamorphic, cross-layer,
  hash-seed reproducibility, and machine-path regression tests for K01-K10.
- Readable intentional snapshots for public exports, registry identities,
  schema fingerprints, structured error codes, enum values, production module
  imports, and public kernel functions.
- Registered unit, contract, property, regression, and slow pytest markers
  plus documented seed and reproduction-blob workflows.
- WP-K10 `MigrationId`, strict migration definitions, policies, requests,
  plans, step results, findings, results, audit results, closed operation and
  coercion enums, and safe canonical migration paths.
- Immutable `MigrationRegistry` with exact endpoint and schema preconditions,
  duplicate graph rejection, reciprocal reverse-edge validation, deterministic
  indexes, and insertion-order-independent fingerprints.
- Pure semantic-cost path resolution, atomic migration dry runs with exact
  source, intermediate, and target Pydantic validation, and structured
  diagnostics that never expose a failed final projection.
- Migration registry audit for false identity edges, multistep route
  ambiguity, reversibility structure, and fingerprint stability.
- Nine valid and twenty-five invalid K10 fixture scenarios plus unit,
  contract, and property tests for all operations, path policies,
  reversibility, rollback, purity, validation, and deterministic fingerprints.
- WP-K09 canonical contract identities, aliases, descriptors, schema
  artifacts, compatibility reports, audit results, and semantic version bump
  recommendations.
- Immutable explicit `ContractRegistry` with 35 public K01-K08 Pydantic
  contracts, deterministic lookups, filters, aliases, schema-backed
  descriptors, and insertion-order-independent catalog fingerprints.
- Deterministic Draft 2020-12 schema generation and idempotent local
  publication of `schemas/manifest.json` and per-contract schema artifacts.
- Conservative structural compatibility analysis and adjacent-version registry
  audit with structured unknown and inadequate-bump findings.
- Valid and invalid K09 fixtures plus unit, contract, publication, schema
  validation, and property tests.
- WP-K08 immutable validation request, policy, finding, stage, and result
  contracts plus the pure `run_validation_pipeline()` orchestration API.
- Canonical six-stage delegation across K03 aggregate validation, K05 patch
  validation and dry runs, K06 transitions, and K07 invariants with normalized
  diagnostics, stable counts, dispositions, and semantic fingerprints.
- Seven valid and fourteen fail-closed validation-pipeline fixture scenarios,
  with unit, contract, and property tests for raw/typed input, stage control,
  registry requirements, continuation, projection, normalization, purity, and
  deterministic round trips.
- Structured K08 errors for invalid requests, missing registries, stage
  failures, and pipeline inconsistencies.
- WP-K07 `InvariantId`, closed invariant enums, immutable definitions,
  evidence, violations, evaluation contexts, and deterministic results.
- Immutable validated `InvariantRegistry` plus pure `evaluate_invariants()` for
  nine canonical current-state and history-aware rules.
- Canonical registry and context manifests, fifteen independent invalid
  invariant fixtures, and unit, contract, and property tests for diagnostics,
  history, blocking policy, selection, purity, and version monotonicity.
- Structured K07 errors for duplicate IDs and keys, invalid definitions,
  evaluation failures, and invariant violations.
- WP-K06 strict transition contracts, `TRN-` identifiers, immutable
  deterministic `TransitionRegistry`, declarative guards and effects, and pure
  `evaluate_transition()` integration with the K05 dry-run engine.
- Canonical transition and request fixtures, invalid transition cases, and
  unit, contract, and property tests for ambiguity, domain scope, guards,
  optimistic preconditions, deterministic evaluation, purity, and versioning.
- Structured transition errors for missing, ambiguous, invalid, guarded, and
  unsupported transition cases.
- WP-K05 `PatchPath`, `PatchOperation`, `StatePatch`,
  `PatchValidationResult`, and `DryRunResult` contracts.
- Segment-based patch scope policy, optimistic state/object preconditions, and
  pure atomic `validate_state_patch()` and `apply_state_patch_dry_run()` APIs.
- Three valid and twelve invalid state-patch fixtures plus unit, contract, and
  property tests for path safety, deep-frozen values, conflicts, aggregate
  validation, determinism, and input-state purity.
- WP-K04 immutable `EventEnvelope`, `EventActor`, `ActorType`, and strict
  `JsonObject` contracts for historical event facts.
- Pure event validators for canonical event types, idempotency keys, timestamp
  ordering, causal references, and recursively strict JSON payloads.
- Valid and invalid event fixtures plus unit, contract, and property tests for
  serialization, immutability, causal rules, fingerprints, and payload safety.
- WP-K03 `ProjectState` aggregate and core records for metadata, profile,
  lifecycle, phase execution, artifacts, requirements, decisions, risks, and
  dependency edges.
- `PhaseId` canonical ID, valid and invalid project-state fixtures, and
  aggregate-focused unit, contract, and property tests.
- WP-K02 strict base contract models: `ContractModel`, `VersionedRecord`, and
  `ImmutableRecord`.
- Deterministic canonical JSON, SHA-256 fingerprints, and UTC normalization
  utilities for contract payloads.
- WP-K01 canonical typed IDs with strict prefixed ULID validation.
- `SemanticVersion` primitive with SemVer 2.0.0 parsing, precedence comparison,
  Pydantic integration, and canonical serialization.
- `TypedReference` and `EvidenceReference` primitives.
- Initial canonical string enums for routes, phases, artifacts, gates,
  approvals, and executions.
- Structured kernel error taxonomy and exception hierarchy.
- Unit and property-based tests for canonical primitives.

### Changed

- Package metadata now advertises Python 3.11 through 3.13, uses
  `src/arch_kernel/__about__.py` as its single static version source, and
  includes `py.typed` plus published JSON Schemas in the wheel.
- WP-K05 test-only and canonically unchanged patches now preserve state
  versions, timestamps, and fingerprints; effective descendant mutations touch
  each affected `VersionedRecord` exactly once per patch.
- WP-K05 rejects internal field mutation of immutable decisions and dependency
  edges while retaining whole-record replacement semantics.
- Generalized K04 frozen JSON validation for arbitrary strict JSON patch values
  while preserving conventional JSON serialization.
- WP-K04 event payloads are now defensively copied and recursively frozen while
  preserving conventional object/array output in JSON serialization.
- **Breaking before 0.1.0:** `PhaseId` now uses `PHS-<ULID>` with target type
  `phase`; `PhaseExecutionId` retains `PHX-<ULID>` with target type
  `phase_execution`.
- **Breaking before 0.1.0:** renamed the K02 model helper to
  `contract_content_fingerprint()` so the required
  `ArtifactRecord.content_fingerprint` field remains unambiguous.
- WP-K02 fingerprints now distinguish complete persisted records from content:
  `contract_content_fingerprint()` excludes only root-level `created_at` and
  `updated_at`; full fingerprints retain every serialized field.

### Fixed

- Corrected pre-release ID semantics, event payload deep immutability, content
  fingerprint exclusions, and nested/test-only patch versioning before the
  first packaged release.

### Security

- Added dependency vulnerability and license inventory gates. Publication
  remains blocked until the owner configures a real private security-reporting
  channel in `SECURITY.md`.

### Internal and Test

- Initial Python repository bootstrap for `arch-kernel`.
- `src` layout with importable `arch_kernel` package.
- Runtime dependency on Pydantic v2.
- Development tooling for pytest, pytest-cov, Hypothesis, Ruff, mypy, and pre-commit.
- Smoke tests for import, version, public exports, and source-layout package discovery.
- Added release tests for metadata, compatibility matrices, archive safety,
  installed behavior, manifest freshness, workflows, policies, and build
  reproducibility.

### Known Limitations

- The kernel is in-memory only and provides no persistence.
- Schema compatibility intentionally covers a conservative structural subset.
- Migrations are explicit only; no automatic repair is provided.
- There is no remote registry, package publication, or release automation that
  writes to an external service.
