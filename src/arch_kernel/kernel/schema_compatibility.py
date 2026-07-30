"""Conservative structural compatibility and registry audit for WP-K09."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from arch_kernel.contracts.registry import (
    CompatibilityLevel,
    ContractIdentity,
    VersionBump,
)
from arch_kernel.contracts.schema import (
    CompatibilityFinding,
    CompatibilityReport,
    ContractRegistryAuditFinding,
    ContractRegistryAuditResult,
    SchemaArtifact,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ErrorCode
from arch_kernel.kernel.fingerprints import canonicalize_json, compute_fingerprint
from arch_kernel.kernel.schema_generation import generate_contract_schema, schema_as_dict

_ZERO_FINGERPRINT = "sha256:" + ("0" * 64)
_IGNORED_KEYS = frozenset({"$id", "$schema", "description", "title"})
_SUPPORTED_KEYS = frozenset(
    {
        "$id",
        "$schema",
        "additionalProperties",
        "anyOf",
        "description",
        "enum",
        "items",
        "maxLength",
        "maximum",
        "minLength",
        "minimum",
        "oneOf",
        "properties",
        "required",
        "title",
        "type",
    }
)


@dataclass(slots=True)
class _Comparison:
    backward: bool = True
    forward: bool = True
    unknown: bool = False


def _finding(
    path: str,
    code: str,
    message: str,
    old_value: object,
    new_value: object,
    *,
    breaking: bool,
) -> CompatibilityFinding:
    return CompatibilityFinding.model_validate(
        {
            "path": path,
            "code": code,
            "message": message,
            "old_value": old_value,
            "new_value": new_value,
            "breaking": breaking,
        }
    )


def _canonical_set(values: list[Any]) -> set[bytes]:
    return {canonicalize_json(value) for value in values}


def _compare_schema(
    old: dict[str, Any],
    new: dict[str, Any],
    path: str,
    comparison: _Comparison,
    findings: list[CompatibilityFinding],
) -> None:
    unsupported = {
        key
        for key in set(old) | set(new)
        if key not in _SUPPORTED_KEYS and old.get(key) != new.get(key)
    }
    for key in sorted(unsupported):
        comparison.backward = False
        comparison.forward = False
        comparison.unknown = True
        findings.append(
            _finding(
                f"{path}/{key}",
                ErrorCode.SCHEMA_COMPATIBILITY_UNKNOWN.value,
                "Changed JSON Schema construct is outside the supported subset.",
                old.get(key),
                new.get(key),
                breaking=True,
            )
        )

    old_type = old.get("type")
    new_type = new.get("type")
    if old_type != new_type:
        old_types = {old_type} if isinstance(old_type, str) else set(old_type or ())
        new_types = {new_type} if isinstance(new_type, str) else set(new_type or ())
        if old_types <= new_types:
            comparison.forward = False
        elif new_types <= old_types:
            comparison.backward = False
        else:
            comparison.backward = False
            comparison.forward = False
        findings.append(
            _finding(
                f"{path}/type",
                "SCHEMA_TYPE_CHANGED",
                "Accepted JSON value types changed.",
                old_type,
                new_type,
                breaking=not comparison.backward,
            )
        )

    old_required = set(old.get("required", ()))
    new_required = set(new.get("required", ()))
    for name in sorted(new_required - old_required):
        comparison.backward = False
        findings.append(
            _finding(
                f"{path}/required/{name}",
                "REQUIRED_PROPERTY_ADDED",
                "A previously optional or absent property is now required.",
                False,
                True,
                breaking=True,
            )
        )
    for name in sorted(old_required - new_required):
        comparison.forward = False
        findings.append(
            _finding(
                f"{path}/required/{name}",
                "REQUIRED_PROPERTY_REMOVED",
                "A previously required property is no longer required.",
                True,
                False,
                breaking=False,
            )
        )

    old_properties = old.get("properties", {})
    new_properties = new.get("properties", {})
    if isinstance(old_properties, dict) and isinstance(new_properties, dict):
        for name in sorted(set(new_properties) - set(old_properties)):
            if old.get("additionalProperties", True) is False:
                comparison.forward = False
            findings.append(
                _finding(
                    f"{path}/properties/{name}",
                    "OPTIONAL_PROPERTY_ADDED",
                    "A property was added to the object schema.",
                    None,
                    new_properties[name],
                    breaking=False,
                )
            )
        for name in sorted(set(old_properties) - set(new_properties)):
            if new.get("additionalProperties", True) is False:
                comparison.backward = False
            findings.append(
                _finding(
                    f"{path}/properties/{name}",
                    "PROPERTY_REMOVED",
                    "A declared property was removed from the object schema.",
                    old_properties[name],
                    None,
                    breaking=not comparison.backward,
                )
            )
        for name in sorted(set(old_properties) & set(new_properties)):
            old_property = old_properties[name]
            new_property = new_properties[name]
            if isinstance(old_property, dict) and isinstance(new_property, dict):
                _compare_schema(
                    old_property,
                    new_property,
                    f"{path}/properties/{name}",
                    comparison,
                    findings,
                )

    old_enum = old.get("enum")
    new_enum = new.get("enum")
    if isinstance(old_enum, list) and isinstance(new_enum, list) and old_enum != new_enum:
        old_values = _canonical_set(old_enum)
        new_values = _canonical_set(new_enum)
        if old_values <= new_values:
            comparison.forward = False
            code = "ENUM_EXPANDED"
        elif new_values <= old_values:
            comparison.backward = False
            code = "ENUM_CONTRACTED"
        else:
            comparison.backward = False
            comparison.forward = False
            code = "ENUM_CHANGED"
        findings.append(
            _finding(
                f"{path}/enum",
                code,
                "Accepted enum values changed.",
                old_enum,
                new_enum,
                breaking=not comparison.backward,
            )
        )

    for key, tightening_is_higher in (
        ("minimum", True),
        ("minLength", True),
        ("maximum", False),
        ("maxLength", False),
    ):
        old_value = old.get(key)
        new_value = new.get(key)
        if old_value == new_value:
            continue
        if old_value is None:
            comparison.backward = False
            tightening = True
        elif new_value is None:
            comparison.forward = False
            tightening = False
        else:
            tightening = new_value > old_value if tightening_is_higher else new_value < old_value
            if tightening:
                comparison.backward = False
            else:
                comparison.forward = False
        findings.append(
            _finding(
                f"{path}/{key}",
                "CONSTRAINT_TIGHTENED" if tightening else "CONSTRAINT_RELAXED",
                f"Schema constraint {key} changed.",
                old_value,
                new_value,
                breaking=tightening,
            )
        )

    old_additional = old.get("additionalProperties", True)
    new_additional = new.get("additionalProperties", True)
    if old_additional != new_additional:
        if old_additional is True and new_additional is False:
            comparison.backward = False
        elif old_additional is False and new_additional is True:
            comparison.forward = False
        else:
            comparison.backward = False
            comparison.forward = False
            comparison.unknown = True
        findings.append(
            _finding(
                f"{path}/additionalProperties",
                "ADDITIONAL_PROPERTIES_CHANGED",
                "Object additional-properties policy changed.",
                old_additional,
                new_additional,
                breaking=not comparison.backward,
            )
        )

    old_items = old.get("items")
    new_items = new.get("items")
    if old_items != new_items:
        if isinstance(old_items, dict) and isinstance(new_items, dict):
            _compare_schema(
                old_items,
                new_items,
                f"{path}/items",
                comparison,
                findings,
            )
        else:
            comparison.backward = False
            comparison.forward = False
            comparison.unknown = True
            findings.append(
                _finding(
                    f"{path}/items",
                    ErrorCode.SCHEMA_COMPATIBILITY_UNKNOWN.value,
                    "Array item schemas are not structurally comparable.",
                    old_items,
                    new_items,
                    breaking=True,
                )
            )

    for keyword in ("oneOf", "anyOf"):
        old_union = old.get(keyword)
        new_union = new.get(keyword)
        if isinstance(old_union, list) and isinstance(new_union, list) and old_union != new_union:
            old_branches = _canonical_set(old_union)
            new_branches = _canonical_set(new_union)
            if old_branches <= new_branches:
                comparison.forward = False
                code = "UNION_BRANCH_ADDED"
            elif new_branches <= old_branches:
                comparison.backward = False
                code = "UNION_BRANCH_REMOVED"
            else:
                comparison.backward = False
                comparison.forward = False
                code = "UNION_BRANCHES_CHANGED"
            findings.append(
                _finding(
                    f"{path}/{keyword}",
                    code,
                    "Union alternatives changed.",
                    old_union,
                    new_union,
                    breaking=not comparison.backward,
                )
            )


def recommend_version_bump(level: CompatibilityLevel) -> VersionBump:
    """Map conservative compatibility to the minimum declared version bump."""

    if level is CompatibilityLevel.IDENTICAL:
        return VersionBump.PATCH
    if level is CompatibilityLevel.BREAKING:
        return VersionBump.MAJOR
    if level is CompatibilityLevel.UNKNOWN:
        return VersionBump.MANUAL_REVIEW
    return VersionBump.MINOR


def compare_schema_artifacts(
    source: SchemaArtifact,
    target: SchemaArtifact,
) -> CompatibilityReport:
    """Compare a closed structural subset; return unknown when unsafe."""

    if source.canonical_name != target.canonical_name:
        raise ValueError("Compatibility requires the same canonical contract name.")
    old = schema_as_dict(source)
    new = schema_as_dict(target)
    semantic_old = {key: value for key, value in old.items() if key not in _IGNORED_KEYS}
    semantic_new = {key: value for key, value in new.items() if key not in _IGNORED_KEYS}
    comparison = _Comparison()
    findings: list[CompatibilityFinding] = []
    if semantic_old != semantic_new:
        _compare_schema(semantic_old, semantic_new, "", comparison, findings)
    findings.sort(key=lambda item: (item.path, item.code))
    if semantic_old == semantic_new:
        level = CompatibilityLevel.IDENTICAL
    elif comparison.unknown:
        level = CompatibilityLevel.UNKNOWN
    elif any(finding.breaking for finding in findings):
        level = CompatibilityLevel.BREAKING
    elif comparison.backward and comparison.forward:
        level = CompatibilityLevel.FULLY_COMPATIBLE
    elif comparison.backward:
        level = CompatibilityLevel.BACKWARD_COMPATIBLE
    elif comparison.forward:
        level = CompatibilityLevel.FORWARD_COMPATIBLE
    else:
        level = CompatibilityLevel.BREAKING
    values = {
        "source": ContractIdentity(
            canonical_name=source.canonical_name,
            version=source.version,
        ),
        "target": ContractIdentity(
            canonical_name=target.canonical_name,
            version=target.version,
        ),
        "level": level,
        "backward_compatible": comparison.backward and not comparison.unknown,
        "forward_compatible": comparison.forward and not comparison.unknown,
        "findings": tuple(findings),
        "minimum_version_bump": recommend_version_bump(level),
        "report_fingerprint": _ZERO_FINGERPRINT,
    }
    provisional = CompatibilityReport.model_validate(values)
    fingerprint = compute_fingerprint(
        provisional.model_dump(mode="json", exclude={"report_fingerprint"})
    )
    return provisional.model_copy(update={"report_fingerprint": fingerprint})


def _adequate_bump(
    source: SemanticVersion,
    target: SemanticVersion,
    required: VersionBump,
) -> bool:
    if target <= source:
        return False
    if required in {VersionBump.MAJOR, VersionBump.MANUAL_REVIEW}:
        return target.major > source.major
    if required is VersionBump.MINOR:
        return target.major > source.major or (
            target.major == source.major and target.minor > source.minor
        )
    return True


def audit_contract_registry(registry: Any) -> ContractRegistryAuditResult:
    """Audit generated schemas and adjacent version bump adequacy."""

    findings: list[ContractRegistryAuditFinding] = []
    pair_count = 0
    canonical_names = {item.descriptor.canonical_name for item in registry.registrations}
    for canonical_name in sorted(canonical_names):
        versions = tuple(
            item
            for item in registry.registrations
            if item.descriptor.canonical_name == canonical_name
        )
        for source_registration, target_registration in pairwise(versions):
            pair_count += 1
            source = generate_contract_schema(source_registration)
            target = generate_contract_schema(target_registration)
            report = compare_schema_artifacts(source, target)
            if not _adequate_bump(
                source.version,
                target.version,
                report.minimum_version_bump,
            ):
                findings.append(
                    ContractRegistryAuditFinding(
                        code=ErrorCode.INADEQUATE_VERSION_BUMP.value,
                        message="Declared version does not satisfy compatibility requirements.",
                        path=f"/contracts/{canonical_name}/{target.version}",
                        blocking=True,
                        source=report.source,
                        target=report.target,
                    )
                )
            if report.level is CompatibilityLevel.UNKNOWN:
                findings.append(
                    ContractRegistryAuditFinding(
                        code=ErrorCode.SCHEMA_COMPATIBILITY_UNKNOWN.value,
                        message="Adjacent schemas require manual compatibility review.",
                        path=f"/contracts/{canonical_name}/{target.version}",
                        blocking=True,
                        source=report.source,
                        target=report.target,
                    )
                )
    rebuilt = type(registry)(tuple(reversed(registry.registrations)))
    if rebuilt.catalog_fingerprint != registry.catalog_fingerprint:
        findings.append(
            ContractRegistryAuditFinding(
                code=ErrorCode.INVALID_CONTRACT_DESCRIPTOR.value,
                message="Catalog fingerprint changes with registry insertion order.",
                path="/catalog_fingerprint",
                blocking=True,
            )
        )
    findings.sort(key=lambda item: (item.path, item.code))
    return ContractRegistryAuditResult(
        success=not any(item.blocking for item in findings),
        findings=tuple(findings),
        catalog_fingerprint=registry.catalog_fingerprint,
        audited_contract_count=len(registry.registrations),
        audited_version_pair_count=pair_count,
    )


__all__ = (
    "audit_contract_registry",
    "compare_schema_artifacts",
    "recommend_version_bump",
)
