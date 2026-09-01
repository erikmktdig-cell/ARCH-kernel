"""Public kernel primitives for ARch."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arch_kernel.kernel.errors import (
    ArchKernelError,
    ErrorCode,
    ErrorDetail,
    EventValidationError,
    IdentifierValidationError,
    ReferenceValidationError,
    Severity,
    VersionValidationError,
)
from arch_kernel.kernel.event_validation import (
    validate_event_causality,
    validate_event_temporal_order,
    validate_event_type,
    validate_idempotency_key,
    validate_json_object,
)
from arch_kernel.kernel.fingerprints import (
    canonicalize_json,
    compute_content_fingerprint,
    compute_fingerprint,
)
from arch_kernel.kernel.time import ensure_utc, utc_now

if TYPE_CHECKING:
    from arch_kernel.contracts.invariants import (
        InvariantEvaluationContext,
        InvariantEvaluationResult,
    )
    from arch_kernel.contracts.migrations import (
        MigrationDefinition,
        MigrationPlan,
        MigrationRegistryAuditResult,
        MigrationRequest,
        MigrationResult,
    )
    from arch_kernel.contracts.patches import (
        DryRunResult,
        PatchOperationType,
        PatchPath,
        PatchValidationResult,
        StatePatch,
    )
    from arch_kernel.contracts.project_state import ProjectState
    from arch_kernel.contracts.registry import (
        CompatibilityLevel,
        ContractRegistration,
        ContractRegistryManifest,
        VersionBump,
    )
    from arch_kernel.contracts.schema import (
        CompatibilityReport,
        ContractRegistryAuditResult,
        SchemaArtifact,
    )
    from arch_kernel.contracts.transitions import (
        TransitionEvaluationResult,
        TransitionRequest,
    )
    from arch_kernel.contracts.validation import (
        ValidationPipelineRequest,
        ValidationPipelineResult,
    )
    from arch_kernel.contracts.workflows import WorkflowDefinition, WorkflowStateRecord
    from arch_kernel.kernel.contract_registry import ContractRegistry
    from arch_kernel.kernel.invariant_registry import InvariantRegistry
    from arch_kernel.kernel.migration_registry import MigrationRegistry
    from arch_kernel.kernel.transition_registry import TransitionRegistry
    from arch_kernel.kernel.workflow_registry import WorkflowDefinitionRegistry


def validate_state_patch(
    state: ProjectState,
    patch: StatePatch,
) -> PatchValidationResult:
    """Validate one patch through the lazily imported patch subsystem."""

    from arch_kernel.kernel.patch_application import validate_state_patch as validate

    return validate(state, patch)


def apply_state_patch_dry_run(
    state: ProjectState,
    patch: StatePatch,
    *,
    evaluated_at: datetime | None = None,
) -> DryRunResult:
    """Dry-run one patch through the lazily imported patch subsystem."""

    from arch_kernel.kernel.patch_application import apply_state_patch_dry_run as apply

    return apply(state, patch, evaluated_at=evaluated_at)


def validate_patch_path_policy(
    path: PatchPath,
    op: PatchOperationType,
) -> ErrorDetail | None:
    """Validate a patch path through the lazily imported path policy."""

    from arch_kernel.kernel.path_policy import validate_patch_path_policy as validate

    return validate(path, op)


def evaluate_transition(
    state: ProjectState,
    request: TransitionRequest,
    registry: TransitionRegistry,
    *,
    evaluated_at: datetime | None = None,
) -> TransitionEvaluationResult:
    """Evaluate one transition through the lazily imported K06 subsystem."""

    from arch_kernel.kernel.transition_evaluation import evaluate_transition as evaluate

    return evaluate(state, request, registry, evaluated_at=evaluated_at)


def evaluate_invariants(
    context: InvariantEvaluationContext,
    registry: InvariantRegistry,
) -> InvariantEvaluationResult:
    """Evaluate invariants through the lazily imported K07 subsystem."""

    from arch_kernel.kernel.invariant_evaluation import evaluate_invariants as evaluate

    return evaluate(context, registry)


def run_validation_pipeline(
    request: ValidationPipelineRequest,
    *,
    transition_registry: TransitionRegistry | None = None,
    invariant_registry: InvariantRegistry | None = None,
) -> ValidationPipelineResult:
    """Run the lazily imported K08 unified validation pipeline."""

    from arch_kernel.kernel.validation_pipeline import run_validation_pipeline as run

    return run(
        request,
        transition_registry=transition_registry,
        invariant_registry=invariant_registry,
    )


def build_builtin_contract_registry() -> ContractRegistry:
    """Build the lazily imported explicit K01-K08 contract registry."""

    from arch_kernel.kernel.contract_registry import build_builtin_contract_registry as build

    return build()


def build_project_state_v1_to_v2_migration() -> MigrationDefinition:
    """Build the explicit ProjectState compatibility migration."""

    from arch_kernel.kernel.project_state_migration import (
        build_project_state_v1_to_v2_migration as build,
    )

    return build()


def initialize_workflow_state(
    definition: WorkflowDefinition,
    *,
    created_at: datetime,
    state_version_created: int,
) -> WorkflowStateRecord:
    """Initialize one generic workflow from an explicit definition."""

    from arch_kernel.kernel.workflow_registry import initialize_workflow_state as initialize

    return initialize(
        definition,
        created_at=created_at,
        state_version_created=state_version_created,
    )


def generate_contract_schema(
    registration: ContractRegistration,
) -> SchemaArtifact:
    """Generate one lazily imported deterministic schema artifact."""

    from arch_kernel.kernel.schema_generation import generate_contract_schema as generate

    return generate(registration)


def generate_registry_schemas(
    registry: ContractRegistry,
) -> tuple[SchemaArtifact, ...]:
    """Generate every registry schema without filesystem effects."""

    from arch_kernel.kernel.schema_generation import generate_registry_schemas as generate

    return generate(registry)


def build_registry_manifest(registry: ContractRegistry) -> ContractRegistryManifest:
    """Build one deterministic registry manifest in memory."""

    from arch_kernel.kernel.schema_generation import build_registry_manifest as build

    return build(registry)


def publish_registry_schemas(
    registry: ContractRegistry,
    output_dir: Path,
) -> ContractRegistryManifest:
    """Publish schemas through the deterministic local K09 writer."""

    from arch_kernel.kernel.schema_generation import publish_registry_schemas as publish

    return publish(registry, output_dir)


def compare_schema_artifacts(
    source: SchemaArtifact,
    target: SchemaArtifact,
) -> CompatibilityReport:
    """Compare schema artifacts through the conservative K09 analyzer."""

    from arch_kernel.kernel.schema_compatibility import compare_schema_artifacts as compare

    return compare(source, target)


def recommend_version_bump(level: CompatibilityLevel) -> VersionBump:
    """Return the minimum conservative semantic-version bump."""

    from arch_kernel.kernel.schema_compatibility import recommend_version_bump as recommend

    return recommend(level)


def audit_contract_registry(
    registry: ContractRegistry,
) -> ContractRegistryAuditResult:
    """Audit registry schemas, ordering, compatibility, and version bumps."""

    from arch_kernel.kernel.schema_compatibility import audit_contract_registry as audit

    return audit(registry)


def resolve_migration_plan(
    request: MigrationRequest,
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationPlan:
    """Resolve one deterministic migration route."""

    from arch_kernel.kernel.migration_planning import resolve_migration_plan as resolve

    return resolve(request, migration_registry, contract_registry)


def run_migration_dry_run(
    request: MigrationRequest,
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationResult:
    """Execute a migration plan without persistence or side effects."""

    from arch_kernel.kernel.migration_execution import run_migration_dry_run as run

    return run(request, migration_registry, contract_registry)


def audit_migration_registry(
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationRegistryAuditResult:
    """Audit migration graph, schemas, and reversibility evidence."""

    from arch_kernel.kernel.migration_audit import audit_migration_registry as audit

    return audit(migration_registry, contract_registry)


def __getattr__(name: str) -> Any:
    if name == "ContractRegistry":
        from arch_kernel.kernel.contract_registry import ContractRegistry

        return ContractRegistry
    if name == "TransitionRegistry":
        from arch_kernel.kernel.transition_registry import TransitionRegistry

        return TransitionRegistry
    if name == "InvariantRegistry":
        from arch_kernel.kernel.invariant_registry import InvariantRegistry

        return InvariantRegistry
    if name == "MigrationRegistry":
        from arch_kernel.kernel.migration_registry import MigrationRegistry

        return MigrationRegistry
    if name == "WorkflowDefinitionRegistry":
        from arch_kernel.kernel.workflow_registry import WorkflowDefinitionRegistry

        return WorkflowDefinitionRegistry
    raise AttributeError(name)


__all__ = (
    "ArchKernelError",
    "ContractRegistry",
    "ErrorCode",
    "ErrorDetail",
    "EventValidationError",
    "IdentifierValidationError",
    "InvariantRegistry",
    "MigrationRegistry",
    "ReferenceValidationError",
    "Severity",
    "TransitionRegistry",
    "VersionValidationError",
    "WorkflowDefinitionRegistry",
    "apply_state_patch_dry_run",
    "audit_contract_registry",
    "audit_migration_registry",
    "build_builtin_contract_registry",
    "build_project_state_v1_to_v2_migration",
    "build_registry_manifest",
    "canonicalize_json",
    "compare_schema_artifacts",
    "compute_content_fingerprint",
    "compute_fingerprint",
    "ensure_utc",
    "evaluate_invariants",
    "evaluate_transition",
    "generate_contract_schema",
    "generate_registry_schemas",
    "initialize_workflow_state",
    "publish_registry_schemas",
    "recommend_version_bump",
    "resolve_migration_plan",
    "run_migration_dry_run",
    "run_validation_pipeline",
    "utc_now",
    "validate_event_causality",
    "validate_event_temporal_order",
    "validate_event_type",
    "validate_idempotency_key",
    "validate_json_object",
    "validate_patch_path_policy",
    "validate_state_patch",
)
