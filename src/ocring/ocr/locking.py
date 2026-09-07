from __future__ import annotations

from .defiance_policy import detect_semantic_contradictions, load_defiance_policy
from .models import (
    ContradictionRecord,
    ContinuityRecord,
    ContinuityState,
    FieldKind,
    FieldLockDecision,
    LockState,
    ScanScope,
    ScanIntegrityReport,
)


REQUIRED_FIELDS = (
    FieldKind.ITEM_NAME,
    FieldKind.ITEM_RARITY,
    FieldKind.ITEM_COUNT,
    FieldKind.ITEM_TYPE,
)


def build_scan_integrity_report(
    continuity_records: tuple[ContinuityRecord, ...],
    *,
    scan_scope: ScanScope = ScanScope.CURRENT_PAGE,
) -> ScanIntegrityReport:
    policy = load_defiance_policy()
    locked_fields: list[FieldLockDecision] = []
    pending_fields: list[FieldLockDecision] = []
    review_required_fields: list[FieldLockDecision] = []
    contradictions: list[ContradictionRecord] = []
    reasons: list[str] = []

    for record in continuity_records:
        for field_kind in REQUIRED_FIELDS + (FieldKind.ITEM_SYNERGY,):
            value = record.fields.get(field_kind, "")
            decision = _decide_field_lock(record, field_kind=field_kind, candidate_value=value)
            if decision.lock_state is LockState.LOCKED:
                locked_fields.append(decision)
            elif decision.lock_state is LockState.BLOCKED_BY_CONFLICT:
                review_required_fields.append(decision)
                contradictions.append(
                    ContradictionRecord(
                        continuity_key=record.continuity_key,
                        field_kind=field_kind,
                        candidate_value=value,
                        contradiction_code="CONTINUITY_CONFLICT",
                        provenance=record.field_provenance.get(field_kind.value, {}),
                        reasons=decision.reasons,
                    )
                )
            else:
                pending_fields.append(decision)

        semantic_contradictions = detect_semantic_contradictions(record.fields, policy=policy)
        for field_kind, candidate_value, contradiction_code in semantic_contradictions:
            contradictions.append(
                ContradictionRecord(
                    continuity_key=record.continuity_key,
                    field_kind=field_kind,
                    candidate_value=candidate_value,
                    contradiction_code=contradiction_code,
                    provenance=record.field_provenance.get(field_kind.value, {}),
                    reasons=(contradiction_code,),
                )
            )
            review_required_fields.append(
                FieldLockDecision(
                    continuity_key=record.continuity_key,
                    field_kind=field_kind,
                    candidate_value=candidate_value,
                    lock_state=LockState.BLOCKED_BY_CONFLICT,
                    provenance=record.field_provenance.get(field_kind.value, {}),
                    reasons=(contradiction_code,),
                )
            )
            reasons.append("SEMANTIC_CONTRADICTION_PRESENT")

        if record.state is ContinuityState.COLLIDED:
            reasons.append("CONTINUITY_CONFLICT_PRESENT")
        elif record.state is ContinuityState.WEAK:
            reasons.append("CONTINUITY_SUPPORT_WEAK")

    completeness_state, completeness_reason = _evaluate_session_completeness(
        continuity_records,
        scan_scope=scan_scope,
        pending_fields=pending_fields,
        review_required_fields=review_required_fields,
    )
    if not continuity_records:
        reasons.append("NO_CONTINUITY_RECORDS")

    return ScanIntegrityReport(
        scan_scope=scan_scope,
        locked_fields=tuple(locked_fields),
        pending_fields=tuple(pending_fields),
        review_required_fields=tuple(review_required_fields),
        contradictions=tuple(contradictions),
        completeness_state=completeness_state,
        completeness_reason=completeness_reason,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _decide_field_lock(
    record: ContinuityRecord,
    *,
    field_kind: FieldKind,
    candidate_value: str,
) -> FieldLockDecision:
    if not candidate_value:
        return FieldLockDecision(
            continuity_key=record.continuity_key,
            field_kind=field_kind,
            candidate_value="",
            lock_state=LockState.MISSING,
            provenance=record.field_provenance.get(field_kind.value, {}),
            reasons=("FIELD_NOT_OBSERVED",),
        )

    if record.state is ContinuityState.COLLIDED:
        return FieldLockDecision(
            continuity_key=record.continuity_key,
            field_kind=field_kind,
            candidate_value=candidate_value,
            lock_state=LockState.BLOCKED_BY_CONFLICT,
            provenance=record.field_provenance.get(field_kind.value, {}),
            reasons=("CONTINUITY_CONFLICT",) + record.reasons,
        )

    if record.state is ContinuityState.STABLE and record.support_count >= 2:
        return FieldLockDecision(
            continuity_key=record.continuity_key,
            field_kind=field_kind,
            candidate_value=candidate_value,
            lock_state=LockState.LOCKED,
            provenance=record.field_provenance.get(field_kind.value, {}),
            reasons=record.reasons,
        )

    return FieldLockDecision(
        continuity_key=record.continuity_key,
        field_kind=field_kind,
        candidate_value=candidate_value,
        lock_state=LockState.SEEK_MORE_EVIDENCE,
        provenance=record.field_provenance.get(field_kind.value, {}),
        reasons=("INSUFFICIENT_TEMPORAL_SUPPORT",) + record.reasons,
    )


def _evaluate_session_completeness(
    continuity_records: tuple[ContinuityRecord, ...],
    *,
    scan_scope: ScanScope,
    pending_fields: list[FieldLockDecision],
    review_required_fields: list[FieldLockDecision],
) -> tuple[str, str]:
    if review_required_fields:
        return "review_required", "review_required_fields_present"
    if not continuity_records:
        return "empty", "no_continuity_records"

    required_pending = [
        field for field in pending_fields if field.field_kind in REQUIRED_FIELDS
    ]
    if required_pending:
        return "partial", "required_fields_pending"
    if scan_scope is ScanScope.CURRENT_PAGE:
        return "page_complete", "current_page_scope"

    completeness_reason = _full_inventory_completion_reason(continuity_records)
    if completeness_reason:
        return "complete", completeness_reason
    return "partial", "scroll_exhaustion_unproven"


def _full_inventory_completion_reason(
    continuity_records: tuple[ContinuityRecord, ...],
) -> str:
    reason_map = {
        "SCROLL_EXHAUSTED": "scroll_exhausted",
        "END_OF_LIST_DETECTED": "end_of_list_detected",
        "PAGE_BOUNDARY_DETECTED": "page_boundary_detected",
        "INFERRED_COMPLETE": "inferred_complete",
    }
    for record in continuity_records:
        for reason in record.reasons:
            mapped = reason_map.get(reason)
            if mapped:
                return mapped
    return ""
