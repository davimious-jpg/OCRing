from __future__ import annotations

from dataclasses import dataclass

from .calibration import CalibrationStore, ConfidenceCalibrator
from .candidate_set import CandidateSet
from .defiance_semantic import DefianceSemantic
from .defiance_policy import detect_semantic_contradictions, load_defiance_policy, validate_candidate
from .independence import build_default_lineage
from .models import AssembledCandidateRecord, ContinuityRecord, FieldKind, RankedFieldCandidate, TemporalFieldAggregate
from .reason_output import build_accept_reason, build_review_reason
from .weight_governance import WeightGovernor


REQUIRED_FIELDS = (
    FieldKind.ITEM_NAME,
    FieldKind.ITEM_RARITY,
    FieldKind.ITEM_COUNT,
    FieldKind.ITEM_TYPE,
)


@dataclass(frozen=True)
class FieldCorrectnessDecision:
    field_kind: str
    state: str
    action: str
    accepted_value: str
    predicted_confidence: float
    calibrated_confidence: float
    candidate_set: list[dict[str, object]]
    contradictions: tuple[str, ...]
    independent_source_count: int
    reason: str
    escalation_chain: tuple[str, ...]


class CorrectnessEngine:
    def __init__(
        self,
        *,
        calibrator: ConfidenceCalibrator | None = None,
        calibration_store: CalibrationStore | None = None,
        governor: WeightGovernor | None = None,
        top_k: int = 3,
        allow_api_escalation: bool = True,
        confidence_threshold: float = 0.80,
    ) -> None:
        self.calibration_store = calibration_store or CalibrationStore()
        self.calibrator = calibrator or ConfidenceCalibrator(store=self.calibration_store)
        self.governor = governor or WeightGovernor(
            profile_weights={
                "classic_ocr": 0.9,
                "dictionary_matcher": 1.0,
                "local_ai_correction": 0.95,
                "api_ai_correction": 0.92,
                "temporal_consensus": 1.1,
                "profile_match": 1.0,
            }
        )
        self.top_k = top_k
        self.allow_api_escalation = allow_api_escalation
        self.confidence_threshold = confidence_threshold

    def evaluate(
        self,
        *,
        ranked_candidates: tuple[RankedFieldCandidate, ...],
        temporal_aggregates: tuple[TemporalFieldAggregate, ...],
        assembled_records: tuple[AssembledCandidateRecord, ...],
        continuity_records: tuple[ContinuityRecord, ...],
        profile_id: str,
    ) -> dict[str, object]:
        field_decisions: list[FieldCorrectnessDecision] = []
        record_decisions: list[dict[str, object]] = []
        escalation_chain: list[str] = []

        continuity_by_slot = {record.row_slots[0] if record.row_slots else 0: record for record in continuity_records}
        aggregate_map = _aggregate_map(temporal_aggregates)
        ranked_map = _ranked_map(ranked_candidates)
        policy = load_defiance_policy()
        semantic = DefianceSemantic.load() if profile_id == "defiance" else None

        for record in assembled_records:
            per_field: list[FieldCorrectnessDecision] = []
            for field_kind in REQUIRED_FIELDS + (FieldKind.ITEM_SYNERGY,):
                decision = self._evaluate_field(
                    record=record,
                    field_kind=field_kind,
                    continuity_record=continuity_by_slot.get(record.row_slot),
                    ranked_candidates=ranked_map.get((record.row_slot, field_kind), ()),
                    aggregates=aggregate_map.get((record.row_slot, field_kind), ()),
                    policy=policy,
                    semantic=semantic,
                )
                if decision is not None:
                    field_decisions.append(decision)
                    per_field.append(decision)
                    for step in decision.escalation_chain:
                        if step not in escalation_chain:
                            escalation_chain.append(step)
            record_decisions.append(self._record_decision(record=row_record_to_key(record), decisions=per_field))

        session_confidence = round(
            (
                sum(record["record_confidence"] for record in record_decisions) / len(record_decisions)
                if record_decisions else 0.0
            ),
            3,
        )
        session_action = _action_threshold(session_confidence, any(record["action"] == "review" for record in record_decisions))
        return {
            "field_correctness": [
                {
                    "field_kind": decision.field_kind,
                    "state": decision.state,
                    "action": decision.action,
                    "accepted_value": decision.accepted_value,
                    "predicted_confidence": decision.predicted_confidence,
                    "calibrated_confidence": decision.calibrated_confidence,
                    "candidate_set": decision.candidate_set,
                    "contradictions": list(decision.contradictions),
                    "independent_source_count": decision.independent_source_count,
                    "reason": decision.reason,
                    "escalation_chain": list(decision.escalation_chain),
                }
                for decision in field_decisions
            ],
            "record_correctness": record_decisions,
            "session_correctness": {
                "session_confidence": session_confidence,
                "action": session_action,
                "record_count": len(record_decisions),
                "escalation_chain": escalation_chain,
            },
            "calibration": self.calibrator.snapshot(),
            "escalation_chain": escalation_chain,
        }

    def _evaluate_field(
        self,
        *,
        record: AssembledCandidateRecord,
        field_kind: FieldKind,
        continuity_record: ContinuityRecord | None,
        ranked_candidates: tuple[RankedFieldCandidate, ...],
        aggregates: tuple[TemporalFieldAggregate, ...],
        policy,
        semantic: DefianceSemantic | None,
    ) -> FieldCorrectnessDecision | None:
        assembled_value = record.fields.get(field_kind, "")
        if not assembled_value and not ranked_candidates and not aggregates:
            return None

        candidate_set = CandidateSet(top_k=self.top_k)
        summary = record.support_summary.get(field_kind.value, {})
        base_confidence = float(summary.get("best_confidence", 0.0))
        support_count = int(summary.get("support_count", 0))
        source_frame_ids = tuple(str(item) for item in summary.get("source_frame_ids", ()))
        source_crop_ids = tuple(str(item) for item in summary.get("source_crop_ids", ()))
        contradictions = detect_semantic_contradictions(record.fields, policy=policy)
        contradiction_codes = tuple(code for contradiction_field, _, code in contradictions if contradiction_field is field_kind)
        valid, validation_reasons = validate_candidate(field_kind, assembled_value, policy=policy) if assembled_value else (False, ("FIELD_NOT_OBSERVED",))
        reference_data_missing = "REFERENCE_DATA_MISSING" in validation_reasons
        correctness_state = "OK"
        semantic_note = ""

        if semantic is not None and field_kind is FieldKind.ITEM_RARITY and assembled_value:
            observed_color = _detail_text(record.field_details.get(FieldKind.ITEM_RARITY.value), "observed_color")
            conflict = semantic.detect_rarity_conflict(assembled_value, observed_color) if observed_color else None
            if conflict is not None:
                correctness_state = "RARITY_CONFLICT"
                semantic_note = conflict.message

        if semantic is not None and field_kind is FieldKind.ITEM_TYPE and assembled_value:
            mod_slot = _detail_text(record.field_details.get("mod_slot"), "source_text")
            warning = semantic.detect_slot_compatibility_warning(mod_slot, assembled_value) if mod_slot else None
            if warning is not None:
                correctness_state = "COMPATIBILITY_WARNING"
                semantic_note = warning.message

        include_dictionary = bool(
            assembled_value
            and valid
            and not reference_data_missing
            and field_kind in {FieldKind.ITEM_NAME, FieldKind.ITEM_RARITY, FieldKind.ITEM_TYPE}
        )
        include_local_ai = bool(continuity_record and continuity_record.support_count >= 2)
        escalation_chain = ["classic_ocr"]
        lineage_node_ids: list[str] = []
        last_dag = None
        for index, frame_id in enumerate(source_frame_ids or (f"frame-missing-{record.row_slot}",)):
            crop_id = source_crop_ids[index] if index < len(source_crop_ids) else f"{frame_id}:{field_kind.value}"
            last_dag, selected_nodes = build_default_lineage(
                frame_id=frame_id,
                crop_id=crop_id,
                engine_name="classic_ocr",
                candidate_value=assembled_value,
                include_dictionary_matcher=include_dictionary,
                include_local_ai=include_local_ai,
            )
            lineage_node_ids.extend(selected_nodes)

        source_keys = ["classic_ocr"]
        if include_dictionary:
            source_keys.append("dictionary_matcher")
        if include_local_ai:
            source_keys.append("local_ai_correction")
            escalation_chain.append("local_ai")
        if support_count >= 2:
            source_keys.append("temporal_consensus")
        if field_kind is FieldKind.ITEM_NAME and assembled_value and not reference_data_missing:
            source_keys.append("profile_match")
        distribution = self.governor.field_weight_distribution(tuple(source_keys))
        predicted_confidence = min(
            1.0,
            base_confidence + (0.05 * support_count) + (0.05 * len(distribution)) - (0.10 * len(contradiction_codes)),
        )
        calibrated_confidence = self.calibrator.calibrate_confidence(
            predicted_confidence,
            source_keys=tuple(source_keys),
            field_type=field_kind.value,
        )
        independent_source_count = last_dag.count_independent_sources(tuple(lineage_node_ids)) if last_dag is not None else 0

        if assembled_value:
            candidate_set.add_candidate(
                candidate_value=assembled_value,
                candidate_score=calibrated_confidence,
                source_lineage=tuple(lineage_node_ids),
                reason="assembled_record_candidate",
                metadata={"distribution": distribution},
            )
        for aggregate in aggregates:
            candidate_set.add_candidate(
                candidate_value=aggregate.candidate_value,
                candidate_score=min(1.0, aggregate.best_confidence + (0.05 * aggregate.independent_support_count)),
                source_lineage=tuple(f"temporal:{frame_id}" for frame_id in aggregate.contributing_frame_ids),
                reason="temporal_candidate",
                metadata={"support_count": aggregate.support_count},
            )
        for candidate in ranked_candidates:
            candidate_set.add_candidate(
                candidate_value=candidate.candidate_value,
                candidate_score=candidate.confidence,
                source_lineage=(candidate.source_crop_id,),
                reason="ranked_candidate",
                metadata={"source_engine": candidate.source_engine},
            )

        action, accepted_value, calibrated_confidence, escalation_chain = self._semantic_allocation_loop(
            field_kind=field_kind,
            assembled_value=assembled_value,
            candidate_set=candidate_set,
            source_keys=source_keys,
            contradiction_codes=contradiction_codes,
            continuity_record=continuity_record,
            valid=valid,
            predicted_confidence=predicted_confidence,
            calibrated_confidence=calibrated_confidence,
            escalation_chain=escalation_chain,
        )

        if reference_data_missing:
            action = "review"
            correctness_state = "REFERENCE_DATA_MISSING"
            if "NEEDS_REVIEW" not in escalation_chain:
                escalation_chain.append("NEEDS_REVIEW")

        if correctness_state in {"RARITY_CONFLICT", "COMPATIBILITY_WARNING"}:
            action = "review"
            if "NEEDS_REVIEW" not in escalation_chain:
                escalation_chain.append("NEEDS_REVIEW")

        evidence_lines = []
        if assembled_value:
            evidence_lines.append(f"OCR matched \"{assembled_value}\" at {round(base_confidence, 2)}")
        if include_dictionary:
            evidence_lines.append("dictionary exact match")
        if include_local_ai:
            evidence_lines.append("local AI agreed")
        if support_count:
            evidence_lines.append(f"{support_count}/{max(1, support_count)} frames agreed")
        if "profile_match" in source_keys:
            evidence_lines.append("known profile token matched")
        if reference_data_missing:
            evidence_lines.append("OCR succeeded but reference data is incomplete")
        if semantic_note:
            evidence_lines.append(semantic_note)
        if contradiction_codes or reference_data_missing:
            uncertainty_lines = tuple([f"contradiction detected: {code}" for code in contradiction_codes] + [reason for reason in validation_reasons if reason])
            reason = build_review_reason(evidence_lines=tuple(evidence_lines), uncertainty_lines=uncertainty_lines)
        elif action == "accept":
            reason = build_accept_reason(candidate_value=accepted_value, evidence_lines=tuple(evidence_lines), contradictions=contradiction_codes)
        else:
            uncertainty_lines = tuple([reason for reason in validation_reasons if reason] or ["no temporal consensus"])
            if semantic_note:
                uncertainty_lines = uncertainty_lines + (semantic_note,)
            if escalation_chain:
                uncertainty_lines = uncertainty_lines + tuple(f"escalation step: {step}" for step in escalation_chain if step != "classic_ocr")
            reason = build_review_reason(evidence_lines=tuple(evidence_lines), uncertainty_lines=uncertainty_lines)

        return FieldCorrectnessDecision(
            field_kind=field_kind.value,
            state=correctness_state,
            action=action,
            accepted_value=accepted_value,
            predicted_confidence=round(predicted_confidence, 3),
            calibrated_confidence=round(calibrated_confidence, 3),
            candidate_set=[
                {
                    "candidate_value": option.candidate_value,
                    "candidate_score": round(option.candidate_score, 3),
                    "source_lineage": list(option.source_lineage),
                    "reason": option.reason,
                    "metadata": option.metadata,
                }
                for option in candidate_set.as_list()
            ],
            contradictions=contradiction_codes,
            independent_source_count=independent_source_count,
            reason=reason,
            escalation_chain=tuple(escalation_chain),
        )

    def _record_decision(self, *, record: dict[str, object], decisions: list[FieldCorrectnessDecision]) -> dict[str, object]:
        if not decisions:
            return {"record": record, "record_confidence": 0.0, "action": "reject", "reasons": ["NO_FIELD_DECISIONS"]}
        confidence = round(sum(item.calibrated_confidence for item in decisions) / len(decisions), 3)
        has_review = any(item.action == "review" for item in decisions)
        has_reject = any(item.action == "reject" for item in decisions)
        action = "accept"
        if has_reject and confidence < 0.45:
            action = "reject"
        elif has_review or has_reject:
            action = "review"
        return {
            "record": record,
            "record_confidence": confidence,
            "action": action,
            "reasons": [item.reason for item in decisions],
            "escalation_chain": list(dict.fromkeys(step for item in decisions for step in item.escalation_chain)),
        }

    def _semantic_allocation_loop(
        self,
        *,
        field_kind: FieldKind,
        assembled_value: str,
        candidate_set: CandidateSet,
        source_keys: list[str],
        contradiction_codes: tuple[str, ...],
        continuity_record: ContinuityRecord | None,
        valid: bool,
        predicted_confidence: float,
        calibrated_confidence: float,
        escalation_chain: list[str],
    ) -> tuple[str, str, float, list[str]]:
        collapsed = candidate_set.collapse()
        accepted_value = collapsed.candidate_value if collapsed is not None else assembled_value
        continuity_state = continuity_record.state.value.upper() if continuity_record is not None else "EMPTY"
        needs_escalation = continuity_state == "COLLIDED" or (continuity_state == "WEAK" and calibrated_confidence < self.confidence_threshold)

        if needs_escalation and "local_ai_correction" not in source_keys:
            source_keys.append("local_ai_correction")
            escalation_chain.append("local_ai")
            calibrated_confidence = self.calibrator.calibrate_confidence(
                min(1.0, predicted_confidence + 0.03),
                source_keys=tuple(source_keys),
                field_type=field_kind.value,
            )
            candidate_set.add_candidate(
                candidate_value=accepted_value,
                candidate_score=calibrated_confidence,
                source_lineage=(f"local_ai:{field_kind.value}:{accepted_value}",),
                reason="local_ai_escalation",
                metadata={"escalated": True},
            )
            collapsed = candidate_set.collapse()
            accepted_value = collapsed.candidate_value if collapsed is not None else accepted_value

        unresolved = contradiction_codes or not valid or calibrated_confidence < self.confidence_threshold
        if unresolved and self.allow_api_escalation and "api_ai_correction" not in source_keys:
            source_keys.append("api_ai_correction")
            escalation_chain.append("api_ai")
            calibrated_confidence = self.calibrator.calibrate_confidence(
                min(1.0, predicted_confidence + 0.05),
                source_keys=tuple(source_keys),
                field_type=field_kind.value,
            )
            candidate_set.add_candidate(
                candidate_value=accepted_value,
                candidate_score=calibrated_confidence,
                source_lineage=(f"api_ai:{field_kind.value}:{accepted_value}",),
                reason="api_ai_escalation",
                metadata={"escalated": True},
            )
            collapsed = candidate_set.collapse()
            accepted_value = collapsed.candidate_value if collapsed is not None else accepted_value

        if contradiction_codes:
            escalation_chain.append("NEEDS_REVIEW")
            return "review", accepted_value, round(calibrated_confidence, 3), list(dict.fromkeys(escalation_chain))
        if not valid and calibrated_confidence < 0.45:
            escalation_chain.append("NEEDS_REVIEW")
            return "reject", accepted_value, round(calibrated_confidence, 3), list(dict.fromkeys(escalation_chain))
        if calibrated_confidence >= 0.85:
            return "accept", accepted_value, round(calibrated_confidence, 3), list(dict.fromkeys(escalation_chain))
        if calibrated_confidence >= 0.45:
            escalation_chain.append("NEEDS_REVIEW")
            return "review", accepted_value, round(calibrated_confidence, 3), list(dict.fromkeys(escalation_chain))
        escalation_chain.append("NEEDS_REVIEW")
        return "reject", accepted_value, round(calibrated_confidence, 3), list(dict.fromkeys(escalation_chain))


def _aggregate_map(aggregates: tuple[TemporalFieldAggregate, ...]) -> dict[tuple[int, FieldKind], tuple[TemporalFieldAggregate, ...]]:
    grouped: dict[tuple[int, FieldKind], list[TemporalFieldAggregate]] = {}
    for aggregate in aggregates:
        grouped.setdefault((aggregate.row_slot, aggregate.field_kind), []).append(aggregate)
    return {key: tuple(value) for key, value in grouped.items()}


def _ranked_map(candidates: tuple[RankedFieldCandidate, ...]) -> dict[tuple[int, FieldKind], tuple[RankedFieldCandidate, ...]]:
    grouped: dict[tuple[int, FieldKind], list[RankedFieldCandidate]] = {}
    for candidate in candidates:
        row_slot = _row_slot(candidate.row_id)
        grouped.setdefault((row_slot, candidate.field_kind), []).append(candidate)
    return {key: tuple(value) for key, value in grouped.items()}


def _row_slot(row_id: str) -> int:
    try:
        return int(str(row_id).rsplit(":", 1)[-1])
    except ValueError:
        return 0


def row_record_to_key(record: AssembledCandidateRecord) -> dict[str, object]:
    return {"row_slot": record.row_slot, "fields": {field.value: value for field, value in record.fields.items()}}


def _action_threshold(session_confidence: float, has_review: bool) -> str:
    if has_review:
        return "review"
    if session_confidence >= 0.85:
        return "accept"
    if session_confidence >= 0.45:
        return "review"
    return "reject"


def _detail_text(detail: object, key: str) -> str:
    if isinstance(detail, dict):
        value = detail.get(key, "")
        return str(value).strip() if value is not None else ""
    if key == "source_text" and detail is not None:
        return str(detail).strip()
    return ""
