from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .evidence_requirements import satisfies_evidence_requirement


class AcceptanceResult(str, Enum):
    ACCEPTED = "ACCEPTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class AcceptanceEvaluation:
    result: AcceptanceResult
    reasons: tuple[str, ...]


def evaluate_acceptance(record: dict[str, Any]) -> AcceptanceEvaluation:
    reasons: list[str] = []
    user_verified = bool(record.get("user_verified"))

    if not _record_definition_known(record):
        reasons.append("RECORD_DEFINITION_UNKNOWN")
        return AcceptanceEvaluation(AcceptanceResult.REJECTED, tuple(reasons))

    required_fields = tuple(str(item) for item in record.get("required_fields", ()))
    field_evidence = record.get("field_evidence", {})
    for field_name in required_fields:
        if not satisfies_evidence_requirement(field_name, _as_dict(field_evidence.get(field_name))):
            reasons.append(f"EVIDENCE_REQUIREMENT_FAILED:{field_name}")

    if bool(record.get("hard_profile_constraint_violated")):
        reasons.append("HARD_PROFILE_CONSTRAINT_VIOLATED")
        return AcceptanceEvaluation(AcceptanceResult.REJECTED, tuple(reasons))

    contradictions = int(record.get("unresolved_contradictions", 0))
    permitted_contradictions = int(record.get("permitted_contradictions", 0))
    if contradictions > permitted_contradictions:
        reasons.append("CONTRADICTIONS_ABOVE_PERMITTED_LEVEL")

    if not bool(record.get("identity_established")):
        reasons.append("IDENTITY_NOT_ESTABLISHED")

    if not bool(record.get("scan_provenance_exists")):
        reasons.append("SCAN_PROVENANCE_MISSING")
        return AcceptanceEvaluation(AcceptanceResult.REJECTED, tuple(reasons))

    acceptance_policy_permits = bool(record.get("acceptance_policy_permits", False))
    if user_verified:
        reasons.append("USER_VERIFIED_OVERRIDE")
        return AcceptanceEvaluation(AcceptanceResult.ACCEPTED, tuple(dict.fromkeys(reasons)))

    if reasons:
        return AcceptanceEvaluation(AcceptanceResult.NEEDS_REVIEW, tuple(dict.fromkeys(reasons)))

    if acceptance_policy_permits:
        reasons.append("ACCEPTANCE_THEOREM_SATISFIED")
        return AcceptanceEvaluation(AcceptanceResult.ACCEPTED, tuple(reasons))

    return AcceptanceEvaluation(AcceptanceResult.NEEDS_REVIEW, ("ACCEPTANCE_POLICY_DENIED",))


def _record_definition_known(record: dict[str, Any]) -> bool:
    if bool(record.get("record_definition_known")):
        return True
    definition_used = str(record.get("definition_used") or "").strip()
    return bool(definition_used and definition_used.upper() != "UNKNOWN")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}
