# arch-kernel

`arch-kernel` is the deterministic, contract-first Python kernel for ARch. It
provides strict immutable contracts, aggregate validation, dry-run patches,
declarative transitions and invariants, a unified validation pipeline, a
versioned contract/schema registry, and explicit migrations. The package is
pre-alpha and intentionally in-memory.

## Current Scope

This repository currently contains:

- A `src`-layout Python package named `arch_kernel`.
- Runtime dependency configuration for Pydantic v2.
- Development tooling for linting, formatting, type checking, testing, coverage,
  and pre-commit hooks.
- Canonical typed IDs with strict ULID validation.
- A strict, comparable `SemanticVersion` primitive.
- `TypedReference` and `EvidenceReference` primitives.
- Initial canonical enums and structured kernel errors.
- Strict `ContractModel`, `VersionedRecord`, and `ImmutableRecord` foundations.
- Deterministic canonical JSON, SHA-256 fingerprints, and UTC timestamp helpers.
- WP-K03 project-state contracts: metadata, profile, lifecycle, phase execution,
  artifacts, requirements, decisions, risks, and dependency edges.
- A valid, deterministic `ProjectState` fixture plus invalid aggregate fixtures.
- WP-K04 immutable event envelopes with actor attribution, causal references,
  strict JSON payloads, and deterministic local event validation.
- WP-K05 declarative state patches with strict paths, optimistic preconditions,
  atomic dry-run simulation, and structured outcomes.
- WP-K06 immutable declarative transitions, deterministic registry lookup,
  aggregate-local guards, scoped effects, and K05-integrated evaluation.
- WP-K07 immutable invariant definitions, deterministic global and historical
  diagnostics, explicit blocking policy, and stable evidence.
- WP-K08 through WP-K12 validation orchestration, schema publication,
  migrations, fixture/property verification, and release hardening.

This repository does not yet contain:

- Routers, agents, persistence, event stores, replay, UI, or LLM calls.
- Persistence-backed state machines, transactional writes, or invariants.
- Remote contract registries, automatic migration repair, or package
  publication.

## Requirements

- Python 3.12 or 3.13. Python 3.12 is the minimum because the approved kernel
  contracts use PEP 695 type-alias syntax.
- `uv` for project, dependency, and environment management.

## Installation

Install a built wheel without importing from the source checkout:

```powershell
uv pip install dist/arch_kernel-0.1.0-py3-none-any.whl
```

For development, install every locked dependency group:

```powershell
uv sync --all-groups
```

## Validation

Run the same quality checks used for the bootstrap:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest -p no:cacheprovider
uv build
uv run python scripts/check_artifacts.py dist
uv run python scripts/check_reproducible_build.py
uv run python scripts/check_release.py
```

The release check never publishes. It fails closed when generated artifacts,
dependency policy, license policy, security governance, archive contents, or
installed behavior are unresolved.

## Package Architecture

- `arch_kernel.contracts` contains strict Pydantic contracts and identities.
- `arch_kernel.kernel` contains pure evaluation, registry, schema, and
  migration functions.
- `arch_kernel.schemas` contains the packaged `py.typed`-compatible public JSON
  Schema catalog for offline use.
- `scripts/` contains development and release tooling and is never imported by
  normal package imports.

The static package version has one source:
`src/arch_kernel/__about__.py`. Builds use `SOURCE_DATE_EPOCH`, generated
catalogs are freshness-checked, and release evidence contains stable
fingerprints for contracts, schemas, fixtures, public APIs, errors, and the
dependency lock.

## Known Limitations

The kernel has no persistence, database, API server, remote registry, or
automatic repair. Schema compatibility is deliberately conservative and
migrations must be registered explicitly. Release checks build candidate
artifacts for inspection but do not publish them.

## Repository Structure

```text
arch-kernel/
├── src/
│   └── arch_kernel/
│       ├── contracts/
│       │   └── enums/
│       ├── kernel/
│       ├── migrations/
│       ├── policies/
│       └── schemas/
├── fixtures/
│   ├── valid/
│   └── invalid/
├── scripts/
└── tests/
    ├── unit/
    ├── contract/
    ├── property/
    └── migration/
```

## Initial Principles

- Contract-first design.
- Deterministic validation.
- Strict typing.
- No persistence in the kernel.
- No LLM calls in the kernel.

## Base Contract Example

```python
from datetime import datetime, timezone

from arch_kernel.contracts import ContractModel, SemanticVersion


class ExampleContract(ContractModel):
    value: str


contract = ExampleContract(
    contract_name="example_contract",
    contract_version=SemanticVersion.parse("1.0.0"),
    schema_uri="urn:arch:contracts:example_contract:1.0.0",
    created_at=datetime.now(timezone.utc),
    value="demo",
)

print(contract.fingerprint())
```

Timestamps must be timezone-aware. They are converted to UTC and fingerprints
always use canonical JSON with UTC expressed as `Z`.

`fingerprint()` and `record_fingerprint()` cover the complete persisted
record. `contract_content_fingerprint()` excludes only root-level `created_at`
and `updated_at`, which makes it suitable for content comparisons. The generic
`compute_fingerprint(value, exclude_fields={...})` API makes any additional
root-level exclusions explicit; it never excludes nested fields implicitly.

## Project State Example

```python
from pathlib import Path

from arch_kernel.contracts import ProjectState


payload = Path("fixtures/valid/minimal_project_state.json").read_text(encoding="utf-8")
state = ProjectState.model_validate_json(payload)

assert state.lifecycle.current_phase_id in state.phase_execution_records
print(state.record_fingerprint())
```

WP-K03 validates only relationships contained in the aggregate, such as registry
keys, lifecycle consistency, internal references, and active baselines. Event
history, state transitions, and historical/global invariants remain deferred to
later work packages.

## Event Envelope Example

```python
from datetime import UTC, datetime

from arch_kernel.contracts import (
    ActorType,
    EventActor,
    EventEnvelope,
    EventId,
    ProjectId,
    SemanticVersion,
    TypedReference,
)

version = SemanticVersion.parse("1.0.0")
now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
project_id = ProjectId.from_str("PRJ-01HZX7M3FQ1T2Q9V8Y6K4C2B1A")

actor = EventActor(
    contract_name="event_actor",
    contract_version=version,
    schema_uri="urn:arch:contracts:event_actor:1.0.0",
    created_at=now,
    actor_type=ActorType.SYSTEM,
    actor_id="arch-kernel",
)
event = EventEnvelope(
    contract_name="event_envelope",
    contract_version=version,
    schema_uri="urn:arch:contracts:event_envelope:1.0.0",
    created_at=now,
    event_id=EventId.from_str("EVT-01HZX7M3FQ1T2Q9V8Y6K4C2B1G"),
    event_type="project.phase.activated",
    project_id=project_id,
    aggregate=TypedReference(target_type="project", target_id=project_id),
    occurred_at=now,
    recorded_at=now,
    actor=actor,
    correlation_id=None,
    causation_id=None,
    idempotency_key="project/phase/activation:001",
    schema_version=version,
    payload={"phase_code": "F02"},
)
```

Root events omit both causal IDs. A caused event supplies both
`correlation_id` and `causation_id`; the two may be equal for the first derived
event. Neither may equal the new event's own ID.

Idempotency keys preserve case and accept 8 to 200 safe ASCII characters from
`A-Z a-z 0-9 . _ : / -`. The contract validates the key but does not persist or
deduplicate events.

`EventEnvelope` and `EventActor` are frozen against field reassignment. Event
payload input is defensively copied and recursively frozen: JSON objects become
`FrozenJsonObject` mappings and arrays become tuples. JSON serialization thaws
them back to conventional objects and arrays. This deep-freeze policy is local
to event payloads and does not change the general `ImmutableRecord` contract.
WP-K04 provides no event store, publication, persistence, replay, or
`ProjectState` event log.

## State Patch Dry Run

```python
from datetime import UTC, datetime

from arch_kernel.contracts import (
    PatchOperation,
    PatchOperationType,
    PatchPath,
    StatePatch,
)
from arch_kernel.kernel import apply_state_patch_dry_run


operation = PatchOperation(
    op=PatchOperationType.REPLACE,
    path=PatchPath.parse("/profile/project_type"),
    value="service",
)

# `state_patch` also carries PatchId, ProjectId, base record version,
# base content fingerprint, creator, scope, and standard contract metadata.
result = apply_state_patch_dry_run(
    state,
    state_patch,
    evaluated_at=datetime(2026, 7, 23, 13, 1, tzinfo=UTC),
)
assert result.projected_state is not state
```

K05 exposes public paths such as `/artifacts/<ArtifactId>` and translates them
to the current aggregate representation internally. Scope matching compares
complete path segments, never textual prefixes.

Every dry run with at least one effective mutation increments
`ProjectState.record_version` exactly once and changes root `updated_at` using
the injected `evaluated_at`, or the patch `created_at` by default. Descendant
mutations inside versioned phase, artifact, requirement, or risk records
increment that record once per patch and update its `updated_at`. Complete
record replacement preserves the version explicitly supplied by the operation.

Successful patches containing only `test` operations, and canonically
identical replacements, preserve all versions, timestamps, and fingerprints
while reporting no `changed_paths`.

Dry runs operate on detached canonical JSON, validate the resulting
`ProjectState`, and never mutate or persist the input. K05 does not perform
authorization, emit events, merge conflicts, evaluate transitions, or run a
global invariant engine.

## Transition Registry

WP-K06 declares transitions as immutable data. `TransitionRegistry` rejects
duplicate identifiers and keys, unsupported domains, invalid enum states,
same-priority route ambiguity, unsafe guard paths, and effects outside the
target domain. Candidate order is always priority, transition key, then
transition ID, independent of insertion order.

```python
from arch_kernel.contracts import TransitionRequest
from arch_kernel.kernel import TransitionRegistry, evaluate_transition


registry = TransitionRegistry(tuple(transition_definitions))
result = evaluate_transition(
    state,
    TransitionRequest.model_validate(request_payload),
    registry,
    evaluated_at=evaluation_time,
)
```

The executable domains are project lifecycle, phase status, artifact status,
risk status, and requirement status. `approval_decision` is reserved in the
contract enum but registry construction rejects it until the aggregate contains
an approval record with a closed resolver.

Guards read only the loaded `ProjectState`; they do not call external policy or
authorization services. Effects preserve declaration order and map only to K05
`replace`, `remove`, and `test` operations. The evaluator derives a stable
`PatchId` from the request ULID, uses a deterministic system actor, forwards
root and target optimistic preconditions, and delegates all mutation,
versioning, timestamp, and aggregate validation behavior to the K05 dry run.

`all_dependencies_satisfied` evaluates required outgoing `requires` edges for
the transition target. A dependency is satisfied only when its referenced
aggregate record is in a closed accepted, approved, completed, implemented,
verified, or closed state. This rule is aggregate-local and intentionally does
not infer external policy validity.

## Generic Workflow State

C01 adds a generic namespaced workflow authority for downstream packages.
Consumers own their namespace, exact state vocabulary, initial state, and
transition policy. Kernel owns only canonical validation, deterministic
definition lookup, optimistic preconditions, effect scope, and patch
evaluation; it contains no consumer-specific workflow values.

```python
from arch_kernel.contracts import (
    SemanticVersion,
    WorkflowDefinition,
    WorkflowId,
    WorkflowNamespace,
    WorkflowStateKey,
)
from arch_kernel.kernel import initialize_workflow_state


definition = WorkflowDefinition(
    contract_name="workflow_definition",
    contract_version=SemanticVersion.parse("1.0.0"),
    schema_uri="urn:arch:contracts:workflow_definition:1.0.0",
    created_at=created_at,
    workflow_id=WorkflowId.generate(),
    namespace=WorkflowNamespace.parse("consumer.delivery"),
    definition_version=SemanticVersion.parse("1.0.0"),
    allowed_states=(
        WorkflowStateKey.parse("draft"),
        WorkflowStateKey.parse("approved"),
    ),
    initial_state=WorkflowStateKey.parse("draft"),
)
record = initialize_workflow_state(
    definition,
    created_at=created_at,
    state_version_created=project.record_version,
)
```

`WorkflowStateRecord` is persisted in `ProjectState.workflow_registry`; metadata
and events are not substitutes for operational authority. A
`WorkflowTransitionDefinition` binds namespace, definition version, definition
fingerprint, source states, and destination to an explicit closed state space.
Effects may replace only `/workflows/{entity_id}/current_state`, and exact
record version and content fingerprint preconditions are mandatory.

Workflow state is not `PhaseStatus`. The existing phase-oriented
`LifecycleState`, `PhaseCode`, `PhaseStatus`, `project_lifecycle`, and
`phase_status` semantics remain distinct and unchanged.

ProjectState contract 2.0.0 requires an explicit workflow collection. The
public K10 migration returned by `build_project_state_v1_to_v2_migration()`
adds an empty collection and updates contract identity; it never infers or
invents workflows from metadata. Initialization is a separate explicit action.

## Invariant Engine

WP-K07 evaluates broader quality, cross-record, release-readiness, and
historical rules without changing `ProjectState`. `InvariantRegistry` validates
the closed `InvariantKind`, expected scope, kind-specific frozen JSON
configuration, unique IDs and keys, then orders definitions by priority, key,
and ID.

```python
from arch_kernel.contracts import InvariantEvaluationContext
from arch_kernel.kernel import InvariantRegistry, evaluate_invariants


context = InvariantEvaluationContext(
    state=state,
    evaluated_at=evaluation_time,
    history=tuple(events),
    previous_snapshots=tuple(snapshots),
)
result = evaluate_invariants(context, InvariantRegistry(tuple(definitions)))
```

The canonical set covers single active phase, lifecycle alignment, baseline
integrity, required dependencies, requirement traceability, critical risk
control, terminal phase consistency, immutable history, and monotonic record
versions. Overlap with K03 and K04 is diagnostic only; their constructibility
validation remains unchanged. JSON context input is validated normally, while
already constructed contract instances are defensively copied and retained so
the engine can diagnose states intentionally constructed without revalidation
in audits and tests.

Lifecycle compatibility is exact and closed: every lifecycle `PhaseStatus`
accepts only the same `PhaseStatus` on its current phase. A logical transition
that changes both fields must therefore generate both effects in one K05 patch.

Event history is copied and normalized by `occurred_at`, then `recorded_at`,
then `event_id`. Causation references, when required, must resolve to an earlier
event in that order. Previous snapshots are supplied oldest-to-newest and
validated by nondecreasing `state_version_updated`; the engine never infers
ordering from object identity.

Severity and blocking are independent policy dimensions.
`InvariantEvaluationResult.success` is false only when at least one violation
comes from a definition with `blocking=True`. Informational and warning
violations remain successful when non-blocking, and every selected enabled
invariant is evaluated even after a blocking finding.

Version monotonicity compares the root aggregate and matching phase, artifact,
requirement, and risk records across adjacent snapshots. Versions cannot
decrease. Equal versions require identical contractual content fingerprints.
The engine reports violations only; it does not generate patches or repairs.

## Unified Validation Pipeline

WP-K08 exposes `run_validation_pipeline()` as the pure orchestration boundary
for contract, aggregate, patch, transition, invariant, and finalization
validation. Every result contains those six stages in that order; stages that
do not apply remain explicit with `executed=False`.

```python
from arch_kernel.contracts import (
    ValidationIntent,
    ValidationPipelineRequest,
)
from arch_kernel.kernel import run_validation_pipeline


result = run_validation_pipeline(
    ValidationPipelineRequest(
        intent=ValidationIntent.VALIDATE_RELEASE,
        evaluated_at=evaluation_time,
        state=state,
    ),
    invariant_registry=invariant_registry,
)
```

The contract stage resolves typed or raw JSON input and rejects conflicting
dual representations. Aggregate validation reconstructs `ProjectState`
through K03. Patch and transition stages delegate to K05 and K06
respectively; transition evaluation reuses the dry run already returned by
K06. The invariant stage delegates each selected original or projected state
to K07.

Defaults are fail-closed. Patch and transition intents evaluate projected
state invariants, release and history intents evaluate the original state, and
state validation evaluates invariants when a registry or explicit selection
is supplied. Missing required registries, malformed contracts, aggregate
failure, and inconsistent projection policy stop downstream work.

All diagnostics normalize to `ValidationFinding` while preserving source
codes, paths, entities, severity, blocking behavior, remediation, invariant
identity, and stable sequence. Non-blocking findings can produce
`accepted_with_findings`; policy may leave them as `accepted` without changing
success. Input fingerprints include policy and registry definitions but omit
the evaluation clock. Result fingerprints recursively omit volatile
`evaluated_at` and `updated_at` metadata while retaining findings,
disposition, versions, summaries, and deterministic outputs.

## Contract Registry and JSON Schemas

WP-K09 and C01 publish an explicit immutable catalog for the 38 public Pydantic
contracts. `ContractRegistry` indexes exact identities,
latest active versions, aliases, Python model types, kinds, statuses, domains,
and tags without reflection or dynamic imports.

```python
from pathlib import Path

from arch_kernel.kernel import (
    audit_contract_registry,
    build_builtin_contract_registry,
    publish_registry_schemas,
)


registry = build_builtin_contract_registry()
audit = audit_contract_registry(registry)
manifest = publish_registry_schemas(registry, Path("schemas"))
```

Canonical identities use `arch.<domain>.<contract_name>`. Each descriptor
binds one semantic version to an explicit Pydantic model, deterministic local
schema ID, relative POSIX filename, model fingerprint, and normalized schema
fingerprint. Registry insertion order cannot affect listing or the catalog
fingerprint.

Schemas use JSON Schema Draft 2020-12. Pydantic remains the normative runtime
validator; published schemas represent structural contracts and do not attempt
to reproduce every aggregate-level Python invariant. Publication writes UTF-8
with LF endings, two-space indentation, a final newline, and `manifest.json`
last. It overwrites only deterministic targets and preserves unrelated files.

Compatibility analysis covers a conservative structural subset: object
properties and required fields, primitive and nullable types, enums, numeric
and string bounds, additional properties, arrays, and safely comparable union
branches. Unsupported changed constructs return `unknown`. Registry audit
checks adjacent versions and requires major bumps for breaking or manually
reviewed changes.

Canonical IDs, `SemanticVersion`, enums, `PatchPath`, base classes, frozen JSON
helpers, and internal Pydantic base models are intentionally not standalone
registry entries. They remain represented inside parent schemas.

## Migration Framework

WP-K10 adds explicit, typed migrations between exact versions in the K09
contract registry. A `MigrationRegistry` is an immutable directed graph:
active definitions must resolve both endpoints, duplicate IDs, keys, and exact
edges are rejected, optional schema fingerprints act as stale-definition
preconditions, and reversible definitions require reciprocal reverse edges.

```python
from arch_kernel.kernel import (
    MigrationRegistry,
    audit_migration_registry,
    resolve_migration_plan,
    run_migration_dry_run,
)


registry = MigrationRegistry(definitions, contract_registry)
plan = resolve_migration_plan(request, registry, contract_registry)
result = run_migration_dry_run(request, registry, contract_registry)
audit = audit_migration_registry(registry, contract_registry)
```

Routing considers only policy-eligible simple paths within `maximum_steps`.
Selection minimizes `(steps, deprecated_edges, lossy_edges,
nonreversible_edges)`. Registry order is stable for iteration, but lexical
order never breaks a semantic tie: equal-cost routes fail as ambiguous.
Downgrades, deprecated definitions, mixed-direction paths, enum passthrough,
lossy paths, and nonreversible paths remain policy-controlled.

Operations are closed declarative data: `add`, `remove`, `replace`, `move`,
`copy`, `rename`, `test`, `set_default`, `map_enum`, and `coerce`. Execution
deep-copies the input, applies every step in memory, optionally validates each
intermediate version, and validates the final payload against the exact target
Pydantic model. Any blocking finding suppresses the final payload; no partial
projection is returned or persisted.

Plan, registry, request, step, payload, and result fingerprints use canonical
JSON. Evaluation time is retained for audit but excluded from semantic result
identity. The framework does not discover, generate, persist, or execute
migrations dynamically and has no callback or plugin surface.

## Fixtures and Property Tests

WP-K11 adds one test-only verification layer across K01-K10. Every JSON
fixture is indexed exactly once by `fixtures/manifest.json` with a stable
dotted key, relative POSIX path, work-package owner, fixture class, expected
outcome, and canonical payload fingerprint. The loader in
`tests.fixture_catalog` validates catalog completeness and returns detached
data.

Reusable bounded Hypothesis strategies live under `tests/strategies/`.
Profiles are selected with `HYPOTHESIS_PROFILE`:

```powershell
$env:HYPOTHESIS_PROFILE = "ci"
uv run pytest -m property
```

The default `local` profile balances exploration and feedback time. `ci`
raises the example count. `debug` disables the example database and keeps
small readable runs. Hypothesis prints reproduction blobs for failures; rerun
with either the reported `@reproduce_failure(...)` decorator or a seed:

```powershell
uv run pytest tests/property/test_cross_kernel_round_trips.py `
  --hypothesis-seed=123456
```

Fixtures and regression snapshots are never updated during normal tests.
Intentional regeneration commands are:

```powershell
uv run python scripts/build_fixture_manifest.py
uv run python scripts/build_regression_snapshots.py
```

Property suites cover canonical serialization, immutable inputs, round trips,
registry ordering, result determinism, patch and transition agreement,
invariant blocking semantics, validation normalization, schema compatibility,
and migration reversibility. Regression snapshots protect exports, exact
contract identities and schema fingerprints, error codes, enums, validation
stages, migration operations, and the production-module coverage inventory.
Focused `-m property` and `-m regression` runs report their partial coverage
without applying the repository-wide threshold; complete `pytest` runs retain
the mandatory 90% branch-coverage gate.

## Contributing

Before opening changes, install dependencies and run the full validation suite:

```powershell
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv build
```

The package is intentionally minimal until later work packages are approved.
