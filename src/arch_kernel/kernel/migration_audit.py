"""Pure migration registry audit."""

from __future__ import annotations

from datetime import UTC, datetime

from arch_kernel.contracts.migrations import (
    MigrationFinding,
    MigrationPolicy,
    MigrationRegistryAuditResult,
    MigrationRequest,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.contract_registry import ContractRegistry
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, Severity
from arch_kernel.kernel.event_validation import freeze_json_object
from arch_kernel.kernel.migration_planning import resolve_migration_plan
from arch_kernel.kernel.migration_registry import MigrationRegistry
from arch_kernel.kernel.schema_compatibility import compare_schema_artifacts
from arch_kernel.kernel.schema_generation import generate_contract_schema


def _finding(
    code: ErrorCode,
    message: str,
    sequence: int,
) -> MigrationFinding:
    return MigrationFinding(
        code=code.value,
        message=message,
        severity=Severity.ERROR,
        blocking=True,
        sequence=sequence,
    )


def audit_migration_registry(
    migration_registry: MigrationRegistry,
    contract_registry: ContractRegistry,
) -> MigrationRegistryAuditResult:
    """Audit identity edges, path ambiguity, and graph fingerprint stability."""

    findings: list[MigrationFinding] = []
    route_count = 0
    for definition in migration_registry.definitions:
        if definition.identity:
            source = contract_registry.get(definition.canonical_name, definition.source_version)
            target = contract_registry.get(definition.canonical_name, definition.target_version)
            if source is not None and target is not None:
                report = compare_schema_artifacts(
                    generate_contract_schema(source),
                    generate_contract_schema(target),
                )
                if report.level.value != "identical":
                    findings.append(
                        _finding(
                            ErrorCode.INVALID_MIGRATION_DEFINITION,
                            "Identity migration requires semantically identical schemas.",
                            len(findings) + 1,
                        )
                    )
    graph_versions: dict[str, set[SemanticVersion]] = {}
    for definition in migration_registry.definitions:
        graph_versions.setdefault(definition.canonical_name, set()).update(
            {definition.source_version, definition.target_version}
        )
    endpoints = tuple(
        (canonical_name, source_version, target_version)
        for canonical_name in sorted(graph_versions)
        for source_version in sorted(graph_versions[canonical_name])
        for target_version in sorted(graph_versions[canonical_name])
        if source_version != target_version
    )
    for canonical_name, source_version, target_version in endpoints:
        route_count += 1
        request = MigrationRequest(
            canonical_name=canonical_name,
            source_version=source_version,
            target_version=target_version,
            source_payload=freeze_json_object({}),
            evaluated_at=datetime(2000, 1, 1, tzinfo=UTC),
            policy=MigrationPolicy(
                validate_source=False,
                validate_target=False,
                allow_deprecated=True,
                allow_downgrade=True,
                allow_mixed_direction=True,
                maximum_steps=128,
            ),
        )
        try:
            resolve_migration_plan(request, migration_registry, contract_registry)
        except ArchKernelError as error:
            if error.detail.code is ErrorCode.AMBIGUOUS_MIGRATION_PATH:
                findings.append(
                    _finding(
                        ErrorCode.AMBIGUOUS_MIGRATION_PATH,
                        error.detail.message,
                        len(findings) + 1,
                    )
                )
    rebuilt = MigrationRegistry(tuple(reversed(migration_registry.definitions)), contract_registry)
    if rebuilt.registry_fingerprint != migration_registry.registry_fingerprint:
        findings.append(
            _finding(
                ErrorCode.MIGRATION_AUDIT_FAILED,
                "Migration registry fingerprint depends on insertion order.",
                len(findings) + 1,
            )
        )
    findings.sort(key=lambda item: (item.code, item.message))
    findings = [
        item.model_copy(update={"sequence": index}) for index, item in enumerate(findings, start=1)
    ]
    return MigrationRegistryAuditResult(
        success=not findings,
        findings=tuple(findings),
        registry_fingerprint=migration_registry.registry_fingerprint,
        audited_migration_count=len(migration_registry.definitions),
        audited_route_count=route_count,
    )


__all__ = ("audit_migration_registry",)
