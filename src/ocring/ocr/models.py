from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReplayFrameMode(str, Enum):
    LIVE_OCR = "live_ocr"
    RANKED_OVERRIDE = "ranked_override"


class FieldKind(str, Enum):
    ITEM_NAME = "item_name"
    ITEM_RARITY = "item_rarity"
    ITEM_COUNT = "item_count"
    ITEM_TYPE = "item_type"
    ITEM_SYNERGY = "item_synergy"


class FrameQualityAction(str, Enum):
    KEEP = "keep"
    DEFER = "defer"
    DROP = "drop"


class EvidenceKind(str, Enum):
    UNRESOLVED = "unresolved"
    ANCHOR = "anchor"
    CONTRADICTION = "contradiction"
    REPRESENTATIVE = "representative"
    DEBUG = "debug"


class PreprocessVariant(str, Enum):
    GRAYSCALE = "grayscale"
    HIGH_CONTRAST = "high_contrast"
    SHARPENED = "sharpened"


class OcrEngineStatus(str, Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


class CandidateStatus(str, Enum):
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class CandidateDecision(str, Enum):
    SELECTED = "selected"
    SECONDARY = "secondary"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class TemporalSupportState(str, Enum):
    SUPPORTED = "supported"
    WEAK = "weak"
    CONFLICTED = "conflicted"


class RecordAssemblyState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CONFLICTED = "conflicted"


class ContinuityState(str, Enum):
    STABLE = "stable"
    COLLIDED = "collided"
    WEAK = "weak"


class ContinuityProgressionState(str, Enum):
    STATIONARY = "stationary"
    SLOT_INCREASE = "slot_increase"
    SLOT_DECREASE = "slot_decrease"
    MIXED = "mixed"


class LockState(str, Enum):
    LOCKED = "locked"
    SEEK_MORE_EVIDENCE = "seek_more_evidence"
    BLOCKED_BY_CONFLICT = "blocked_by_conflict"
    MISSING = "missing"


class ScanScope(str, Enum):
    CURRENT_PAGE = "current_page"
    FULL_INVENTORY = "full_inventory"


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass(frozen=True)
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_dict(self) -> dict[str, int]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass(frozen=True)
class FrameImage:
    path: str
    width: int
    height: int


@dataclass(frozen=True)
class FrameRecord:
    frame_id: str
    session_id: str
    profile_id: str
    timestamp_utc: str
    image: FrameImage
    inventory_region: Rect
    detector_name: str = "default"


@dataclass(frozen=True)
class QualityMetrics:
    sharpness: float
    motion_penalty: float
    contrast: float
    occlusion_penalty: float
    partial_row_penalty: float
    action: FrameQualityAction
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RowZone:
    row_id: str
    row_bounds: Rect
    fields: dict[FieldKind, Rect]


@dataclass(frozen=True)
class CropEvidence:
    crop_id: str
    frame_id: str
    row_id: str
    field_kind: FieldKind
    region: Rect
    evidence_kind: EvidenceKind
    quality_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreprocessedRegion:
    variant: PreprocessVariant
    region: Rect
    width: int
    height: int
    stats: dict[str, float]


@dataclass(frozen=True)
class PreparedFieldCrop:
    crop_id: str
    row_id: str
    field_kind: FieldKind
    variant: PreprocessVariant
    source_region: Rect
    width: int
    height: int
    stats: dict[str, float]


@dataclass(frozen=True)
class OcrAttempt:
    crop_id: str
    row_id: str
    field_kind: FieldKind
    variant: PreprocessVariant
    engine_name: str
    status: OcrEngineStatus
    raw_text: str
    normalized_text: str
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldCandidate:
    crop_id: str
    row_id: str
    field_kind: FieldKind
    candidate_value: str
    source_variant: PreprocessVariant
    source_engine: str
    status: CandidateStatus
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedFieldCandidate:
    row_id: str
    field_kind: FieldKind
    candidate_value: str
    source_crop_id: str
    source_variant: PreprocessVariant
    source_engine: str
    decision: CandidateDecision
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemporalFieldAggregate:
    temporal_key: str
    row_slot: int
    field_kind: FieldKind
    candidate_value: str
    support_state: TemporalSupportState
    support_count: int
    independent_support_count: int
    best_confidence: float
    contributing_frame_ids: tuple[str, ...]
    contributing_row_ids: tuple[str, ...]
    contributing_crop_ids: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    # Evidence-quality assessment, independent of temporal stability.
    # "" / default means not assessed (non-ITEM_NAME fields, or an aggregate built
    # before this gate existed) and must never be treated as a failure by a reader.
    text_quality_state: str = ""
    text_quality_score: float = 0.0
    text_quality_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssembledCandidateRecord:
    row_slot: int
    profile_id: str
    state: RecordAssemblyState
    fields: dict[FieldKind, str]
    support_summary: dict[str, dict[str, float | int | str]]
    source_frame_ids: tuple[str, ...]
    source_row_ids: tuple[str, ...]
    missing_fields: tuple[FieldKind, ...]
    overlap_provenance: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    truth_state: str = "observed"
    progression_reason: str = ""
    profile_version: str = ""
    scan_timestamp: str = ""
    definition_used: str = ""
    field_details: dict[str, Any] = field(default_factory=dict)
    semantic_notes: tuple[str, ...] = ()
    # Stable, unique-per-record identity key. Defaults to "" for
    # any construction site that doesn't set it (older tests, other builders);
    # the assembler always sets it to str(row_slot) in its default (legacy)
    # mode, so one record per row_slot still means one distinct id there. In
    # temporal-identity-aware (recorded scrolling) mode, a single row_slot can
    # produce multiple records - one per temporally distinct item_name
    # identity that occupied that screen position at a different time - and
    # each gets its own id here instead of colliding on row_slot.
    temporal_identity_id: str = ""


@dataclass(frozen=True)
class FrameOverlap:
    frame_a_id: str
    frame_b_id: str
    overlap_rows: tuple[tuple[int, int], ...]
    overlap_confidence: float


@dataclass(frozen=True)
class ContinuityRecord:
    continuity_key: str
    profile_id: str
    row_slots: tuple[int, ...]
    state: ContinuityState
    progression_state: ContinuityProgressionState
    support_count: int
    frame_ids: tuple[str, ...]
    source_record_count: int
    sightings: tuple[tuple[str, int], ...]
    fields: dict[FieldKind, str]
    field_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldLockDecision:
    continuity_key: str
    field_kind: FieldKind
    candidate_value: str
    lock_state: LockState
    provenance: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class OcrEngineSummary:
    engine_name: str
    available: bool
    reason: str = ""


@dataclass(frozen=True)
class ContradictionRecord:
    continuity_key: str
    field_kind: FieldKind
    candidate_value: str
    contradiction_code: str
    provenance: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanIntegrityReport:
    scan_scope: ScanScope
    locked_fields: tuple[FieldLockDecision, ...]
    pending_fields: tuple[FieldLockDecision, ...]
    review_required_fields: tuple[FieldLockDecision, ...]
    contradictions: tuple[ContradictionRecord, ...]
    completeness_state: str
    completeness_reason: str = ""
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticReport:
    frame: FrameRecord
    replay_mode: ReplayFrameMode
    ocr_engine: OcrEngineSummary
    quality: QualityMetrics
    row_zones: tuple[RowZone, ...]
    preprocessed_regions: tuple[PreprocessedRegion, ...]
    prepared_crops: tuple[PreparedFieldCrop, ...]
    ocr_attempts: tuple[OcrAttempt, ...]
    field_candidates: tuple[FieldCandidate, ...]
    ranked_candidates: tuple[RankedFieldCandidate, ...]
    retained_evidence: tuple[CropEvidence, ...]
    screen_class: str = "inventory"
    screen_reason: str = ""
    hold_reason: str = ""
    recognition_mode: str = "Classic-Only"
    selected_detail_correlation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame": {
                "frame_id": self.frame.frame_id,
                "session_id": self.frame.session_id,
                "profile_id": self.frame.profile_id,
                "timestamp_utc": self.frame.timestamp_utc,
                "image": {
                    "path": self.frame.image.path,
                    "width": self.frame.image.width,
                    "height": self.frame.image.height,
                },
                "inventory_region": self.frame.inventory_region.as_dict(),
                "detector_name": self.frame.detector_name,
            },
            "replay_mode": self.replay_mode.value,
            "ocr_engine": {
                "engine_name": self.ocr_engine.engine_name,
                "available": self.ocr_engine.available,
                "reason": self.ocr_engine.reason,
            },
            "screen_class": self.screen_class,
            "screen_reason": self.screen_reason,
            "hold_reason": self.hold_reason,
            "recognition_mode": self.recognition_mode,
            "selected_detail_correlation": _to_jsonable(self.selected_detail_correlation),
            "quality": {
                "sharpness": self.quality.sharpness,
                "motion_penalty": self.quality.motion_penalty,
                "contrast": self.quality.contrast,
                "occlusion_penalty": self.quality.occlusion_penalty,
                "partial_row_penalty": self.quality.partial_row_penalty,
                "action": self.quality.action.value,
                "reasons": list(self.quality.reasons),
            },
            "row_zones": [
                {
                    "row_id": zone.row_id,
                    "row_bounds": zone.row_bounds.as_dict(),
                    "fields": {field.value: rect.as_dict() for field, rect in zone.fields.items()},
                }
                for zone in self.row_zones
            ],
            "preprocessed_regions": [
                {
                    "variant": region.variant.value,
                    "region": region.region.as_dict(),
                    "width": region.width,
                    "height": region.height,
                    "stats": region.stats,
                }
                for region in self.preprocessed_regions
            ],
            "prepared_crops": [
                {
                    "crop_id": crop.crop_id,
                    "row_id": crop.row_id,
                    "field_kind": crop.field_kind.value,
                    "variant": crop.variant.value,
                    "source_region": crop.source_region.as_dict(),
                    "width": crop.width,
                    "height": crop.height,
                    "stats": crop.stats,
                }
                for crop in self.prepared_crops
            ],
            "ocr_attempts": [
                {
                    "crop_id": attempt.crop_id,
                    "row_id": attempt.row_id,
                    "field_kind": attempt.field_kind.value,
                    "variant": attempt.variant.value,
                    "engine_name": attempt.engine_name,
                    "status": attempt.status.value,
                    "raw_text": attempt.raw_text,
                    "normalized_text": attempt.normalized_text,
                    "confidence": attempt.confidence,
                    "reasons": list(attempt.reasons),
                }
                for attempt in self.ocr_attempts
            ],
            "field_candidates": [
                {
                    "crop_id": candidate.crop_id,
                    "row_id": candidate.row_id,
                    "field_kind": candidate.field_kind.value,
                    "candidate_value": candidate.candidate_value,
                    "source_variant": candidate.source_variant.value,
                    "source_engine": candidate.source_engine,
                    "status": candidate.status.value,
                    "confidence": candidate.confidence,
                    "reasons": list(candidate.reasons),
                }
                for candidate in self.field_candidates
            ],
            "ranked_candidates": [
                {
                    "row_id": candidate.row_id,
                    "field_kind": candidate.field_kind.value,
                    "candidate_value": candidate.candidate_value,
                    "source_crop_id": candidate.source_crop_id,
                    "source_variant": candidate.source_variant.value,
                    "source_engine": candidate.source_engine,
                    "decision": candidate.decision.value,
                    "confidence": candidate.confidence,
                    "reasons": list(candidate.reasons),
                }
                for candidate in self.ranked_candidates
            ],
            "retained_evidence": [
                {
                    "crop_id": evidence.crop_id,
                    "frame_id": evidence.frame_id,
                    "row_id": evidence.row_id,
                    "field_kind": evidence.field_kind.value,
                    "region": evidence.region.as_dict(),
                    "evidence_kind": evidence.evidence_kind.value,
                    "quality_score": evidence.quality_score,
                    "metadata": evidence.metadata,
                }
                for evidence in self.retained_evidence
            ],
        }


@dataclass(frozen=True)
class SessionDiagnosticReport:
    profile_id: str
    profile_version: dict[str, Any]
    frame_reports: tuple[DiagnosticReport, ...]
    temporal_aggregates: tuple[TemporalFieldAggregate, ...]
    assembled_records: tuple[AssembledCandidateRecord, ...]
    continuity_records: tuple[ContinuityRecord, ...]
    scan_integrity: ScanIntegrityReport
    frame_overlaps: tuple[FrameOverlap, ...] = ()
    overlap_count: int = 0
    overlap_confidence: float = 0.0
    continuity_summary: str = "CONTINUITY_LOST"

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": _to_jsonable(self.profile_version),
            "frame_reports": [report.as_dict() for report in self.frame_reports],
            "temporal_aggregates": [
                {
                    "temporal_key": aggregate.temporal_key,
                    "row_slot": aggregate.row_slot,
                    "field_kind": aggregate.field_kind.value,
                    "candidate_value": aggregate.candidate_value,
                    "support_state": aggregate.support_state.value,
                    "support_count": aggregate.support_count,
                    "independent_support_count": aggregate.independent_support_count,
                    "best_confidence": aggregate.best_confidence,
                    "contributing_frame_ids": list(aggregate.contributing_frame_ids),
                    "contributing_row_ids": list(aggregate.contributing_row_ids),
                    "contributing_crop_ids": list(aggregate.contributing_crop_ids),
                    "reasons": list(aggregate.reasons),
                    "text_quality_state": aggregate.text_quality_state,
                    "text_quality_score": aggregate.text_quality_score,
                    "text_quality_reasons": list(aggregate.text_quality_reasons),
                }
                for aggregate in self.temporal_aggregates
            ],
            "assembled_records": [
                {
                    "row_slot": record.row_slot,
                    "profile_id": record.profile_id,
                    "state": record.state.value,
                    "fields": {field.value: value for field, value in record.fields.items()},
                    "support_summary": _to_jsonable(record.support_summary),
                    "source_frame_ids": list(record.source_frame_ids),
                    "source_row_ids": list(record.source_row_ids),
                    "missing_fields": [field.value for field in record.missing_fields],
                    "overlap_provenance": _to_jsonable(record.overlap_provenance),
                    "reasons": list(record.reasons),
                    "truth_state": record.truth_state,
                    "progression_reason": record.progression_reason,
                    "profile_version": record.profile_version,
                    "scan_timestamp": record.scan_timestamp,
                    "definition_used": record.definition_used,
                    "field_details": _to_jsonable(record.field_details),
                    "semantic_notes": list(record.semantic_notes),
                    "temporal_identity_id": record.temporal_identity_id,
                }
                for record in self.assembled_records
            ],
            "continuity_records": [
                {
                    "continuity_key": record.continuity_key,
                    "profile_id": record.profile_id,
                    "row_slots": list(record.row_slots),
                    "state": record.state.value,
                    "progression_state": record.progression_state.value,
                    "support_count": record.support_count,
                    "frame_ids": list(record.frame_ids),
                    "source_record_count": record.source_record_count,
                    "sightings": [
                        {"frame_id": frame_id, "row_slot": row_slot}
                        for frame_id, row_slot in record.sightings
                    ],
                    "fields": {field.value: value for field, value in record.fields.items()},
                    "field_provenance": _to_jsonable(record.field_provenance),
                    "reasons": list(record.reasons),
                }
                for record in self.continuity_records
            ],
            "frame_overlaps": [
                {
                    "frame_a_id": overlap.frame_a_id,
                    "frame_b_id": overlap.frame_b_id,
                    "overlap_rows": [
                        {"row_slot_a": row_slot_a, "row_slot_b": row_slot_b}
                        for row_slot_a, row_slot_b in overlap.overlap_rows
                    ],
                    "overlap_confidence": overlap.overlap_confidence,
                }
                for overlap in self.frame_overlaps
            ],
            "overlap_count": self.overlap_count,
            "overlap_confidence": self.overlap_confidence,
            "continuity_summary": self.continuity_summary,
            "scan_integrity": {
                "scan_scope": self.scan_integrity.scan_scope.value,
                "locked_fields": [
                    {
                        "continuity_key": field.continuity_key,
                        "field_kind": field.field_kind.value,
                        "candidate_value": field.candidate_value,
                        "lock_state": field.lock_state.value,
                        "provenance": _to_jsonable(field.provenance),
                        "reasons": list(field.reasons),
                    }
                    for field in self.scan_integrity.locked_fields
                ],
                "pending_fields": [
                    {
                        "continuity_key": field.continuity_key,
                        "field_kind": field.field_kind.value,
                        "candidate_value": field.candidate_value,
                        "lock_state": field.lock_state.value,
                        "provenance": _to_jsonable(field.provenance),
                        "reasons": list(field.reasons),
                    }
                    for field in self.scan_integrity.pending_fields
                ],
                "review_required_fields": [
                    {
                        "continuity_key": field.continuity_key,
                        "field_kind": field.field_kind.value,
                        "candidate_value": field.candidate_value,
                        "lock_state": field.lock_state.value,
                        "provenance": _to_jsonable(field.provenance),
                        "reasons": list(field.reasons),
                    }
                    for field in self.scan_integrity.review_required_fields
                ],
                "contradictions": [
                    {
                        "continuity_key": contradiction.continuity_key,
                        "field_kind": contradiction.field_kind.value,
                        "candidate_value": contradiction.candidate_value,
                        "contradiction_code": contradiction.contradiction_code,
                        "provenance": _to_jsonable(contradiction.provenance),
                        "reasons": list(contradiction.reasons),
                    }
                    for contradiction in self.scan_integrity.contradictions
                ],
                "completeness_state": self.scan_integrity.completeness_state,
                "completeness_reason": self.scan_integrity.completeness_reason,
                "reasons": list(self.scan_integrity.reasons),
            },
        }
