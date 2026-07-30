"""Pure bounded migration path resolution."""

from __future__ import annotations

from collections import deque

from arch_kernel.contracts.migrations import (
    MigrationDefinition,
    MigrationDirection,
    MigrationPlan,
    MigrationRequest,
    MigrationStatus,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.migration_registry import MigrationRegistry


def _planning_error(code: ErrorCode, message: str) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=code,
            message=message,
            path=("migration_plan",),
            entity_type="migration",
            severity=Severity.ERROR,
        )
    )


def _eligible(
    definition: MigrationDefinition,
    request: MigrationRequest,
) -> bool:
    policy = request.policy
    if definition.status is MigrationStatus.DEPRECATED and not policy.allow_deprecated:
        return False
    if definition.status is MigrationStatus.RESERVED:
        return False
    if policy.require_lossless and not definition.lossless:
        return False
    if policy.require_reversible and not definition.reversible:
        return False
    if (
        request.selected_migration_ids is not None
        and definition.migration_id not in request.selected_migration_ids
    ):
        return False
    return not (
        request.selected_migration_keys is not None
        and definition.key not in request.selected_migration_keys
    )


def _cost(path: tuple[MigrationDefinition, ...]) -> tuple[int, int, int, int]:
    return (
        len(path),
        sum(item.status is MigrationStatus.DEPRECATED for item in path),
        sum(not item.lossless for item in path),
        sum(not item.reversible for item in path),
    )


def _has_route_ignoring_step_limit(
    request: MigrationRequest,
    migration_registry: MigrationRegistry,
    direction: MigrationDirection,
) -> bool:
    queue: deque[tuple[SemanticVersion, frozenset[SemanticVersion]]] = deque(
        [(request.source_version, frozenset({request.source_version}))]
    )
    while queue:
        version, visited = queue.popleft()
        for edge in migration_registry.outgoing(request.canonical_name, version):
            if not _eligible(edge, request):
                continue
            if not request.policy.allow_mixed_direction and edge.direction is not direction:
                continue
            if edge.target_version in visited:
                continue
            if edge.target_version == request.target_version:
                return True
            queue.append((edge.target_version, visited | {edge.target_version}))
    return False


def resolve_migration_plan(
    request: MigrationRequest,
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationPlan:
    """Resolve one unique minimum semantic-cost simple route."""

    source = contract_registry.get(request.canonical_name, request.source_version)
    target = contract_registry.get(request.canonical_name, request.target_version)
    if source is None or target is None:
        raise _planning_error(
            ErrorCode.MIGRATION_ENDPOINT_NOT_FOUND,
            "Migration request endpoint is absent from ContractRegistry.",
        )
    if request.expected_registry_fingerprint is not None and (
        request.expected_registry_fingerprint != migration_registry.registry_fingerprint
    ):
        raise _planning_error(
            ErrorCode.MIGRATION_PRECONDITION_FAILED,
            "Expected migration registry fingerprint is stale.",
        )
    if request.source_version == request.target_version:
        fingerprint_values = {
            "canonical_name": request.canonical_name,
            "source_version": request.source_version,
            "target_version": request.target_version,
            "migration_ids": (),
            "version_path": (request.source_version,),
            "total_steps": 0,
            "direction": None,
            "lossless": True,
            "reversible": True,
            "registry_fingerprint": migration_registry.registry_fingerprint,
        }
        return MigrationPlan(
            canonical_name=request.canonical_name,
            source_version=request.source_version,
            target_version=request.target_version,
            migration_ids=(),
            version_path=(request.source_version,),
            total_steps=0,
            direction=None,
            lossless=True,
            reversible=True,
            registry_fingerprint=migration_registry.registry_fingerprint,
            plan_fingerprint=compute_fingerprint(fingerprint_values),
        )
    direction = (
        MigrationDirection.UPGRADE
        if request.target_version > request.source_version
        else MigrationDirection.DOWNGRADE
    )
    if direction is MigrationDirection.DOWNGRADE and not request.policy.allow_downgrade:
        raise _planning_error(
            ErrorCode.MIGRATION_POLICY_VIOLATION,
            "Downgrade routing is disabled by policy.",
        )
    queue: deque[
        tuple[
            SemanticVersion,
            tuple[MigrationDefinition, ...],
            frozenset[SemanticVersion],
        ]
    ] = deque([(request.source_version, (), frozenset({request.source_version}))])
    routes: list[tuple[MigrationDefinition, ...]] = []
    while queue:
        version, path, visited = queue.popleft()
        if len(path) >= request.policy.maximum_steps:
            continue
        for edge in migration_registry.outgoing(request.canonical_name, version):
            if not _eligible(edge, request):
                continue
            if not request.policy.allow_mixed_direction and edge.direction is not direction:
                continue
            if edge.target_version in visited:
                continue
            candidate = (*path, edge)
            if edge.target_version == request.target_version:
                routes.append(candidate)
                continue
            queue.append(
                (
                    edge.target_version,
                    candidate,
                    visited | {edge.target_version},
                )
            )
    if not routes:
        if _has_route_ignoring_step_limit(
            request,
            migration_registry,
            direction,
        ):
            raise _planning_error(
                ErrorCode.MIGRATION_POLICY_VIOLATION,
                "Eligible migration path exceeds maximum_steps.",
            )
        raise _planning_error(
            ErrorCode.MIGRATION_PATH_NOT_FOUND,
            "No eligible migration path exists.",
        )
    best_cost = min(_cost(route) for route in routes)
    best = tuple(route for route in routes if _cost(route) == best_cost)
    if len(best) != 1:
        raise _planning_error(
            ErrorCode.AMBIGUOUS_MIGRATION_PATH,
            "Multiple migration paths have equal semantic cost.",
        )
    selected = best[0]
    version_path = (
        request.source_version,
        *(item.target_version for item in selected),
    )
    fingerprint_values = {
        "canonical_name": request.canonical_name,
        "source_version": request.source_version,
        "target_version": request.target_version,
        "migration_ids": tuple(item.migration_id for item in selected),
        "version_path": version_path,
        "total_steps": len(selected),
        "direction": direction,
        "lossless": all(item.lossless for item in selected),
        "reversible": all(item.reversible for item in selected),
        "registry_fingerprint": migration_registry.registry_fingerprint,
    }
    routing_constraints = request.policy.model_dump(mode="json")
    return MigrationPlan(
        canonical_name=request.canonical_name,
        source_version=request.source_version,
        target_version=request.target_version,
        migration_ids=tuple(item.migration_id for item in selected),
        version_path=version_path,
        total_steps=len(selected),
        direction=direction,
        lossless=all(item.lossless for item in selected),
        reversible=all(item.reversible for item in selected),
        registry_fingerprint=migration_registry.registry_fingerprint,
        plan_fingerprint=compute_fingerprint(
            {
                **fingerprint_values,
                "routing_constraints": routing_constraints,
            }
        ),
    )


__all__ = ("resolve_migration_plan",)
