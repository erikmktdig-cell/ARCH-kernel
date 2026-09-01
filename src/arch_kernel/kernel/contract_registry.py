"""Immutable deterministic registry of explicitly approved contract models."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel

from arch_kernel.contracts import (
    ArtifactRecord,
    DecisionRecord,
    DependencyEdge,
    DryRunResult,
    EventActor,
    EventEnvelope,
    EvidenceReference,
    GuardEvaluation,
    InvariantDefinition,
    InvariantEvaluationContext,
    InvariantEvaluationResult,
    InvariantEvidence,
    InvariantViolation,
    LifecycleState,
    PatchOperation,
    PatchValidationResult,
    PhaseExecutionRecord,
    ProjectMetadata,
    ProjectProfile,
    ProjectState,
    RequirementRecord,
    RiskRecord,
    StatePatch,
    TransitionDefinition,
    TransitionEffect,
    TransitionEvaluationResult,
    TransitionGuard,
    TransitionRequest,
    TransitionTarget,
    TypedReference,
    ValidationFinding,
    ValidationPipelinePolicy,
    ValidationPipelineRequest,
    ValidationPipelineResult,
    ValidationStageResult,
    WorkflowDefinition,
    WorkflowStateRecord,
    WorkflowTransitionDefinition,
)
from arch_kernel.contracts.registry import (
    ContractDescriptor,
    ContractKind,
    ContractRegistration,
    ContractStatus,
)
from arch_kernel.contracts.versions import SemanticVersion
from arch_kernel.kernel.errors import ArchKernelError, ErrorCode, ErrorDetail, Severity
from arch_kernel.kernel.fingerprints import compute_fingerprint
from arch_kernel.kernel.schema_generation import generate_contract_schema

_VERSION = SemanticVersion.parse("1.0.0")
_PROJECT_STATE_VERSION = SemanticVersion.parse("2.0.0")
_ZERO_FINGERPRINT = "sha256:" + ("0" * 64)


def _registry_error(
    code: ErrorCode,
    message: str,
    *,
    actual: str | None = None,
) -> ArchKernelError:
    return ArchKernelError(
        ErrorDetail(
            code=code,
            message=message,
            path=("registrations",),
            entity_type="contract_registry",
            actual=actual,
            severity=Severity.ERROR,
        )
    )


class ContractRegistry:
    """Validated immutable indexes and schema-backed catalog fingerprint."""

    __slots__ = (
        "_by_alias",
        "_by_identity",
        "_by_model",
        "_versions",
        "catalog_fingerprint",
        "descriptors",
        "registrations",
    )

    registrations: tuple[ContractRegistration, ...]
    descriptors: tuple[ContractDescriptor, ...]
    catalog_fingerprint: str
    _by_identity: Mapping[tuple[str, SemanticVersion], ContractRegistration]
    _by_alias: Mapping[str, str]
    _by_model: Mapping[type[BaseModel], ContractRegistration]
    _versions: Mapping[str, tuple[ContractRegistration, ...]]

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ContractRegistry is immutable.")

    def __init__(self, registrations: tuple[ContractRegistration, ...]) -> None:
        if not isinstance(registrations, tuple):
            raise TypeError("ContractRegistry registrations must be a tuple.")
        ordered = tuple(
            sorted(
                registrations,
                key=lambda item: (
                    item.descriptor.canonical_name,
                    item.descriptor.version,
                ),
            )
        )
        identities: dict[tuple[str, SemanticVersion], ContractRegistration] = {}
        aliases: dict[str, str] = {}
        models: dict[type[BaseModel], ContractRegistration] = {}
        versions: dict[str, list[ContractRegistration]] = {}
        canonical_names = {item.descriptor.canonical_name for item in ordered}
        schema_ids: set[str] = set()
        filenames: set[str] = set()
        for registration in ordered:
            descriptor = registration.descriptor
            identity = (descriptor.canonical_name, descriptor.version)
            if identity in identities:
                raise _registry_error(
                    ErrorCode.DUPLICATE_CONTRACT_IDENTITY,
                    "Duplicate canonical contract name and version.",
                    actual=f"{descriptor.canonical_name}@{descriptor.version}",
                )
            if registration.model in models:
                raise _registry_error(
                    ErrorCode.CONTRACT_MODEL_MISMATCH,
                    "A Pydantic model type cannot represent multiple contract identities.",
                    actual=f"{registration.model.__module__}.{registration.model.__qualname__}",
                )
            if (
                descriptor.python_module != registration.model.__module__
                or descriptor.python_qualname != registration.model.__qualname__
            ):
                raise _registry_error(
                    ErrorCode.CONTRACT_MODEL_MISMATCH,
                    "Descriptor Python identity does not match its registered model.",
                    actual=f"{descriptor.python_module}.{descriptor.python_qualname}",
                )
            if descriptor.schema_id in schema_ids or descriptor.schema_filename in filenames:
                raise _registry_error(
                    ErrorCode.INVALID_CONTRACT_DESCRIPTOR,
                    "Schema IDs and filenames must be unique registry-wide.",
                    actual=descriptor.schema_id,
                )
            artifact = generate_contract_schema(registration)
            if artifact.schema_fingerprint != descriptor.schema_fingerprint:
                raise _registry_error(
                    ErrorCode.CONTRACT_MODEL_MISMATCH,
                    "Descriptor schema fingerprint does not match the registered model.",
                    actual=descriptor.canonical_name,
                )
            identities[identity] = registration
            models[registration.model] = registration
            versions.setdefault(descriptor.canonical_name, []).append(registration)
            schema_ids.add(descriptor.schema_id)
            filenames.add(descriptor.schema_filename)
            for alias in descriptor.aliases:
                if alias.alias in aliases:
                    raise _registry_error(
                        ErrorCode.DUPLICATE_CONTRACT_ALIAS,
                        "Contract aliases must be unique registry-wide.",
                        actual=alias.alias,
                    )
                if alias.alias in canonical_names:
                    raise _registry_error(
                        ErrorCode.CONTRACT_ALIAS_COLLISION,
                        "Contract alias collides with a canonical name.",
                        actual=alias.alias,
                    )
                aliases[alias.alias] = descriptor.canonical_name
        object.__setattr__(self, "registrations", ordered)
        object.__setattr__(self, "descriptors", tuple(item.descriptor for item in ordered))
        object.__setattr__(self, "_by_identity", MappingProxyType(identities))
        object.__setattr__(self, "_by_alias", MappingProxyType(aliases))
        object.__setattr__(self, "_by_model", MappingProxyType(models))
        object.__setattr__(
            self,
            "_versions",
            MappingProxyType({key: tuple(value) for key, value in versions.items()}),
        )
        catalog = tuple(
            {
                "canonical_name": item.descriptor.canonical_name,
                "version": str(item.descriptor.version),
                "descriptor_fingerprint": item.descriptor.semantic_fingerprint(),
                "schema_fingerprint": item.descriptor.schema_fingerprint,
            }
            for item in ordered
        )
        object.__setattr__(self, "catalog_fingerprint", compute_fingerprint(catalog))

    def get(
        self,
        canonical_name: str,
        version: SemanticVersion,
    ) -> ContractRegistration | None:
        return self._by_identity.get((canonical_name, version))

    def latest_active(self, canonical_name: str) -> ContractRegistration | None:
        candidates = tuple(
            item
            for item in self._versions.get(canonical_name, ())
            if item.descriptor.status is ContractStatus.ACTIVE
        )
        return candidates[-1] if candidates else None

    def resolve(
        self,
        name_or_alias: str,
        version: SemanticVersion | None = None,
    ) -> ContractRegistration | None:
        canonical_name = self._by_alias.get(name_or_alias, name_or_alias)
        if version is not None:
            return self.get(canonical_name, version)
        return self.latest_active(canonical_name)

    def get_by_model(self, model: type[BaseModel]) -> ContractRegistration | None:
        return self._by_model.get(model)

    def filter(
        self,
        *,
        kind: ContractKind | None = None,
        status: ContractStatus | None = None,
        domain: str | None = None,
        tag: str | None = None,
    ) -> tuple[ContractRegistration, ...]:
        domain_prefix = f"arch.{domain}." if domain is not None else None
        return tuple(
            item
            for item in self.registrations
            if (kind is None or item.descriptor.kind is kind)
            and (status is None or item.descriptor.status is status)
            and (domain_prefix is None or item.descriptor.canonical_name.startswith(domain_prefix))
            and (tag is None or tag in item.descriptor.tags)
        )


def _snake_case(name: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _registration(
    model: type[BaseModel],
    domain: str,
    kind: ContractKind,
) -> ContractRegistration:
    version = _PROJECT_STATE_VERSION if model is ProjectState else _VERSION
    canonical_name = f"arch.{domain}.{_snake_case(model.__name__)}"
    identity = {
        "python_module": model.__module__,
        "python_qualname": model.__qualname__,
    }
    descriptor = ContractDescriptor(
        canonical_name=canonical_name,
        version=version,
        kind=kind,
        status=ContractStatus.ACTIVE,
        python_module=model.__module__,
        python_qualname=model.__qualname__,
        schema_id=f"https://schemas.arch.local/{canonical_name}/{version}",
        schema_filename=f"contracts/{canonical_name}.{version}.schema.json",
        title=model.__name__,
        description=(model.__doc__ or f"Public {model.__name__} contract.").strip(),
        tags=(domain,),
        model_fingerprint=compute_fingerprint(identity),
        schema_fingerprint=_ZERO_FINGERPRINT,
        descriptor_version=_VERSION,
    )
    provisional = ContractRegistration(descriptor, model)
    artifact = generate_contract_schema(provisional)
    return ContractRegistration(
        descriptor.model_copy(update={"schema_fingerprint": artifact.schema_fingerprint}),
        model,
    )


_BUILTIN_MODELS: tuple[tuple[type[BaseModel], str, ContractKind], ...] = (
    (TypedReference, "reference", ContractKind.PRIMITIVE),
    (EvidenceReference, "reference", ContractKind.PRIMITIVE),
    (ProjectMetadata, "project", ContractKind.RECORD),
    (ProjectProfile, "project", ContractKind.RECORD),
    (LifecycleState, "project", ContractKind.RECORD),
    (PhaseExecutionRecord, "project", ContractKind.RECORD),
    (ArtifactRecord, "project", ContractKind.RECORD),
    (RequirementRecord, "project", ContractKind.RECORD),
    (RiskRecord, "project", ContractKind.RECORD),
    (DecisionRecord, "project", ContractKind.RECORD),
    (DependencyEdge, "project", ContractKind.RECORD),
    (WorkflowDefinition, "workflow", ContractKind.RECORD),
    (WorkflowStateRecord, "workflow", ContractKind.RECORD),
    (ProjectState, "project", ContractKind.AGGREGATE),
    (EventActor, "event", ContractKind.RECORD),
    (EventEnvelope, "event", ContractKind.EVENT),
    (PatchOperation, "patch", ContractKind.COMMAND),
    (StatePatch, "patch", ContractKind.COMMAND),
    (PatchValidationResult, "patch", ContractKind.RESULT),
    (DryRunResult, "patch", ContractKind.RESULT),
    (TransitionTarget, "transition", ContractKind.COMMAND),
    (TransitionGuard, "transition", ContractKind.POLICY),
    (TransitionEffect, "transition", ContractKind.COMMAND),
    (TransitionDefinition, "transition", ContractKind.RECORD),
    (WorkflowTransitionDefinition, "transition", ContractKind.RECORD),
    (TransitionRequest, "transition", ContractKind.COMMAND),
    (GuardEvaluation, "transition", ContractKind.DIAGNOSTIC),
    (TransitionEvaluationResult, "transition", ContractKind.RESULT),
    (InvariantDefinition, "invariant", ContractKind.RECORD),
    (InvariantEvidence, "invariant", ContractKind.DIAGNOSTIC),
    (InvariantViolation, "invariant", ContractKind.DIAGNOSTIC),
    (InvariantEvaluationContext, "invariant", ContractKind.COMMAND),
    (InvariantEvaluationResult, "invariant", ContractKind.RESULT),
    (ValidationFinding, "validation", ContractKind.DIAGNOSTIC),
    (ValidationStageResult, "validation", ContractKind.RESULT),
    (ValidationPipelinePolicy, "validation", ContractKind.POLICY),
    (ValidationPipelineRequest, "validation", ContractKind.COMMAND),
    (ValidationPipelineResult, "validation", ContractKind.RESULT),
)


def build_builtin_contract_registry() -> ContractRegistry:
    """Build the explicit K01-K08 public contract registry."""

    return ContractRegistry(
        tuple(_registration(model, domain, kind) for model, domain, kind in _BUILTIN_MODELS)
    )


__all__ = ("ContractRegistry", "build_builtin_contract_registry")
