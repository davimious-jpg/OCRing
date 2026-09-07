from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import FieldCandidate, OcrAttempt, PreparedFieldCrop
from .normalize import build_field_candidates
from .ocr_runner import run_ocr_attempts
from .recognition_flow_controller import RecognitionDecision, RecognitionFlowController
from .recognition_router import RecognitionRoute, RecognitionRouter
from .profile_version import ProfileVersion
from .settings import RecognitionSettings


@dataclass(frozen=True)
class OrchestratedRecognitionRecord:
    crop_id: str
    route: RecognitionRoute
    decision: RecognitionDecision
    raw_ocr: str
    local_ai_candidate: str
    api_ai_candidate: str
    final_status: str
    candidate: FieldCandidate
    provenance: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OrchestratedRecognitionResult:
    ocr_attempts: tuple[OcrAttempt, ...]
    field_candidates: tuple[FieldCandidate, ...]
    records: tuple[OrchestratedRecognitionRecord, ...]
    recognition_mode_used: str


class RecognitionOrchestrator:
    def __init__(
        self,
        *,
        router: RecognitionRouter | None = None,
        flow_controller: RecognitionFlowController | None = None,
    ) -> None:
        self.router = router or RecognitionRouter()
        self.flow_controller = flow_controller or RecognitionFlowController()

    def run(
        self,
        *,
        image_path: Path,
        prepared_crops: tuple[PreparedFieldCrop, ...],
        profile_id: str,
        settings: RecognitionSettings,
        contract: dict[str, object],
        quality_metrics: object | None = None,
        profile_version: str | None = None,
    ) -> OrchestratedRecognitionResult:
        attempts = run_ocr_attempts(image_path, prepared_crops)
        candidates = build_field_candidates(attempts, profile_id=profile_id)
        resolved_profile_version = profile_version or ProfileVersion.for_scan(profile_id).profile_version
        quality_score = float(getattr(quality_metrics, "sharpness", 0.7))
        motion_blur = float(getattr(quality_metrics, "motion_penalty", 0.0))
        records: list[OrchestratedRecognitionRecord] = []
        mode_labels: set[str] = set()

        for attempt, candidate in zip(attempts, candidates):
            field_name = attempt.field_kind.value
            route = self.router.route(field_name, {})
            dictionary_match = candidate.candidate_value in set(_allowed_values(contract, field_name))
            field_validity = bool(candidate.candidate_value)
            allow_local_ai = settings.recognition_mode in {"Balanced", "Accurate", "Custom"}
            allow_api_ai = settings.recognition_mode in {"Accurate", "Custom"} and settings.api_escalation != "Never"
            if settings.recognition_mode == "Offline":
                allow_api_ai = False
            if settings.recognition_mode == "Fast":
                allow_local_ai = False
            decision = self.flow_controller.decide(
                image_quality=quality_score,
                motion_blur=motion_blur,
                ocr_confidence=float(candidate.confidence),
                dictionary_match=dictionary_match,
                field_validity=field_validity,
                continuity_confidence=0.8,
                local_ai_available=allow_local_ai,
                api_ai_allowed=allow_api_ai,
                queue_pressure=0.1,
            )
            local_ai_candidate = ""
            api_ai_candidate = ""
            final_status = "ok" if candidate.candidate_value else "needs_review"
            if decision.selected_tier == "local_ai":
                local_ai_candidate = _local_ai_fallback(candidate.candidate_value or attempt.normalized_text, field_name, contract)
                final_status = "ok" if local_ai_candidate else "needs_review"
                mode_labels.add("Local-AI")
            elif decision.selected_tier == "api_ai":
                local_ai_candidate = _local_ai_fallback(candidate.candidate_value or attempt.normalized_text, field_name, contract)
                api_ai_candidate = local_ai_candidate or candidate.candidate_value
                final_status = "ok" if api_ai_candidate else "needs_review"
                mode_labels.add("Hybrid")
            elif decision.selected_tier == "classic_ocr":
                mode_labels.add("Classic-Only")
            else:
                mode_labels.add("Offline" if settings.recognition_mode == "Offline" else "Classic-Only")
            records.append(
                OrchestratedRecognitionRecord(
                    crop_id=attempt.crop_id,
                    route=route,
                    decision=decision,
                    raw_ocr=attempt.normalized_text,
                    local_ai_candidate=local_ai_candidate,
                    api_ai_candidate=api_ai_candidate,
                    final_status=final_status,
                    candidate=candidate,
                    provenance={
                        "field_kind": field_name,
                        "contract_bound": bool(contract),
                        "profile_version": resolved_profile_version,
                        "primary_path": list(route.primary_path),
                        "fallback_path": list(route.fallback_path),
                    },
                )
            )

        if not mode_labels:
            mode_labels.add("Offline" if settings.recognition_mode == "Offline" else "Classic-Only")
        recognition_mode_used = (
            "Hybrid"
            if "Hybrid" in mode_labels
            else "Local-AI"
            if "Local-AI" in mode_labels
            else "Offline"
            if settings.recognition_mode == "Offline"
            else "Classic-Only"
        )
        return OrchestratedRecognitionResult(
            ocr_attempts=attempts,
            field_candidates=candidates,
            records=tuple(records),
            recognition_mode_used=recognition_mode_used,
        )


def _allowed_values(contract: dict[str, object], field_name: str) -> tuple[str, ...]:
    mapping = {
        "item_name": "allowed_names",
        "item_rarity": "allowed_rarities",
        "item_synergy": "allowed_synergies",
        "item_count": "allowed_counts",
        "item_type": "allowed_types",
    }
    values = contract.get(mapping.get(field_name, ""), ())
    return tuple(str(value) for value in values)


def _local_ai_fallback(value: str, field_name: str, contract: dict[str, object]) -> str:
    cleaned = " ".join(str(value).split()).strip()
    if not cleaned:
        return ""
    allowed = _allowed_values(contract, field_name)
    if not allowed:
        return cleaned
    lowered = cleaned.lower()
    for option in allowed:
        if option.lower() == lowered:
            return option
    for option in allowed:
        if lowered in option.lower() or option.lower() in lowered:
            return option
    return ""
