from __future__ import annotations

from collections import defaultdict
from hashlib import sha1

from .models import (
    AssembledCandidateRecord,
    ContinuityProgressionState,
    ContinuityRecord,
    ContinuityState,
    FrameOverlap,
    FieldKind,
    RecordAssemblyState,
)


IDENTITY_FIELDS = (
    FieldKind.ITEM_NAME,
    FieldKind.ITEM_TYPE,
    FieldKind.ITEM_RARITY,
    FieldKind.ITEM_COUNT,
)
MIN_STRONG_OVERLAP_CONFIDENCE = 0.75
WEAK_OVERLAP_CONFIDENCE = 0.25


def build_continuity_records(
    records: tuple[AssembledCandidateRecord, ...],
    *,
    profile_id: str,
    frame_order: dict[str, int] | None = None,
) -> tuple[ContinuityRecord, ...]:
    frame_order = frame_order or {}
    grouped: dict[str, list[AssembledCandidateRecord]] = defaultdict(list)
    for record in records:
        grouped[_continuity_key(record)].append(record)

    continuity_records: list[ContinuityRecord] = []
    for continuity_key, options in grouped.items():
        row_slots = tuple(sorted({record.row_slot for record in options}))
        sightings = _build_sightings(options, frame_order=frame_order)
        frame_ids = _extract_frame_ids(options)
        fields = _best_fields(options)
        field_provenance = _build_field_provenance(options, fields)
        support_count = _support_count(options)
        progression_state = _derive_progression_state(sightings)
        state, reasons = _derive_continuity_state(options, row_slots=row_slots, support_count=support_count)
        continuity_records.append(
            ContinuityRecord(
                continuity_key=continuity_key,
                profile_id=profile_id,
                row_slots=row_slots,
                state=state,
                progression_state=progression_state,
                support_count=support_count,
                frame_ids=frame_ids,
                source_record_count=len(options),
                sightings=sightings,
                fields=fields,
                field_provenance=field_provenance,
                reasons=reasons,
            )
        )

    return tuple(
        sorted(
            continuity_records,
            key=lambda record: (-record.support_count, record.continuity_key),
        )
    )


def analyze_frame_overlaps(
    continuity_records: tuple[ContinuityRecord, ...],
    *,
    frame_order: dict[str, int] | None = None,
) -> tuple[tuple[ContinuityRecord, ...], tuple[FrameOverlap, ...], int, float, str]:
    frame_order = frame_order or {}
    ordered_frames = [
        frame_id
        for frame_id, _ in sorted(frame_order.items(), key=lambda item: item[1])
    ]
    overlaps: list[FrameOverlap] = []
    overlap_pairs_by_record: dict[str, dict[tuple[str, int, str, int], float]] = defaultdict(dict)

    for frame_a_id, frame_b_id in zip(ordered_frames, ordered_frames[1:]):
        matched_rows: list[tuple[int, int]] = []
        confidences: list[float] = []
        for record in continuity_records:
            row_map = {frame_id: row_slot for frame_id, row_slot in record.sightings}
            if frame_a_id not in row_map or frame_b_id not in row_map:
                continue
            row_slot_a = row_map[frame_a_id]
            row_slot_b = row_map[frame_b_id]
            matched_rows.append((row_slot_a, row_slot_b))
            confidences.append(_identity_similarity(record))
            overlap_pairs_by_record[record.continuity_key][(frame_a_id, row_slot_a, frame_b_id, row_slot_b)] = _identity_similarity(record)
        if matched_rows:
            overlaps.append(
                FrameOverlap(
                    frame_a_id=frame_a_id,
                    frame_b_id=frame_b_id,
                    overlap_rows=tuple(sorted(matched_rows)),
                    overlap_confidence=round(sum(confidences) / len(confidences), 3),
                )
            )

    updated_records = tuple(
        _apply_overlap_progression(record, overlap_pairs_by_record.get(record.continuity_key, {}))
        for record in continuity_records
    )
    overlap_count = sum(len(overlap.overlap_rows) for overlap in overlaps)
    overlap_confidence = round(sum(overlap.overlap_confidence for overlap in overlaps) / len(overlaps), 3) if overlaps else 0.0
    if overlaps and overlap_confidence >= MIN_STRONG_OVERLAP_CONFIDENCE:
        continuity_summary = "OVERLAP_DETECTED"
    elif overlaps and overlap_confidence >= WEAK_OVERLAP_CONFIDENCE:
        continuity_summary = "OVERLAP_WEAK"
    else:
        continuity_summary = "CONTINUITY_LOST"
    return updated_records, tuple(overlaps), overlap_count, overlap_confidence, continuity_summary


def estimate_motion_level(frame_overlaps: tuple[FrameOverlap, ...], *, max_rows: int = 8) -> float:
    if not frame_overlaps:
        return 0.0
    deltas: list[float] = []
    for overlap in frame_overlaps:
        for row_slot_a, row_slot_b in overlap.overlap_rows:
            deltas.append(abs(row_slot_b - row_slot_a) / max(1, max_rows))
    if not deltas:
        return 0.0
    return round(sum(deltas) / len(deltas), 3)


def continuity_health(continuity_records: tuple[ContinuityRecord, ...]) -> str:
    if any(record.state is ContinuityState.COLLIDED for record in continuity_records):
        return "CONFLICTED"
    if any(record.state is ContinuityState.WEAK for record in continuity_records):
        return "WEAK"
    if continuity_records:
        return "OK"
    return "EMPTY"


def _continuity_key(record: AssembledCandidateRecord) -> str:
    identity_parts: list[str] = []
    for field in IDENTITY_FIELDS:
        value = record.fields.get(field, "").strip()
        if value:
            identity_parts.append(f"{field.value}={value.lower()}")
    if not identity_parts:
        identity_parts.append(f"row_slot={record.row_slot}")
    digest = sha1("|".join(identity_parts).encode("utf-8")).hexdigest()
    return digest[:20]


def _extract_frame_ids(records: list[AssembledCandidateRecord]) -> tuple[str, ...]:
    frame_ids: list[str] = []
    for record in records:
        for frame_id in record.source_frame_ids:
            if frame_id and frame_id not in frame_ids:
                frame_ids.append(frame_id)
    return tuple(frame_ids)


def _build_sightings(
    records: list[AssembledCandidateRecord],
    *,
    frame_order: dict[str, int],
) -> tuple[tuple[str, int], ...]:
    sightings: list[tuple[int, str, int]] = []
    for record in records:
        first_order = min((frame_order.get(frame_id, 10_000) for frame_id in record.source_frame_ids), default=10_000)
        first_frame_id = record.source_frame_ids[0] if record.source_frame_ids else ""
        sightings.append((first_order, first_frame_id, record.row_slot))
    sightings.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple((frame_id, row_slot) for _, frame_id, row_slot in sightings)


def _best_fields(records: list[AssembledCandidateRecord]) -> dict[FieldKind, str]:
    chosen: dict[FieldKind, tuple[str, float, int]] = {}
    for record in records:
        for field, value in record.fields.items():
            summary = record.support_summary.get(field.value, {})
            confidence = float(summary.get("best_confidence", 0.0))
            support_count = int(summary.get("support_count", 0))
            current = chosen.get(field)
            if current is None or (support_count, confidence) > (current[2], current[1]):
                chosen[field] = (value, confidence, support_count)
    return {field: payload[0] for field, payload in chosen.items()}


def _support_count(records: list[AssembledCandidateRecord]) -> int:
    best = 0
    for record in records:
        record_support = max(
            (int(summary.get("support_count", 0)) for summary in record.support_summary.values()),
            default=0,
        )
        best = max(best, record_support)
    return best


def _build_field_provenance(
    records: list[AssembledCandidateRecord],
    fields: dict[FieldKind, str],
) -> dict[str, dict[str, object]]:
    provenance: dict[str, dict[str, object]] = {}
    for field_kind, candidate_value in fields.items():
        source_frame_ids: list[str] = []
        source_row_ids: list[str] = []
        source_crop_ids: list[str] = []
        best_confidence = 0.0
        support_count = 0
        independent_support_count = 0

        for record in records:
            if record.fields.get(field_kind) != candidate_value:
                continue
            summary = record.support_summary.get(field_kind.value, {})
            for frame_id in summary.get("source_frame_ids", ()):
                if frame_id and frame_id not in source_frame_ids:
                    source_frame_ids.append(str(frame_id))
            for row_id in summary.get("source_row_ids", ()):
                if row_id and row_id not in source_row_ids:
                    source_row_ids.append(str(row_id))
            for crop_id in summary.get("source_crop_ids", ()):
                if crop_id and crop_id not in source_crop_ids:
                    source_crop_ids.append(str(crop_id))
            best_confidence = max(best_confidence, float(summary.get("best_confidence", 0.0)))
            support_count = max(support_count, int(summary.get("support_count", 0)))
            independent_support_count = max(
                independent_support_count,
                int(summary.get("independent_support_count", 0)),
            )

        provenance[field_kind.value] = {
            "candidate_value": candidate_value,
            "source_frame_ids": source_frame_ids,
            "source_row_ids": source_row_ids,
            "source_crop_ids": source_crop_ids,
            "best_confidence": best_confidence,
            "support_count": support_count,
            "independent_support_count": independent_support_count,
        }
    return provenance


def _derive_continuity_state(
    records: list[AssembledCandidateRecord],
    *,
    row_slots: tuple[int, ...],
    support_count: int,
) -> tuple[ContinuityState, tuple[str, ...]]:
    reasons: list[str] = []
    if any(record.state is RecordAssemblyState.CONFLICTED for record in records):
        reasons.append("SOURCE_RECORD_CONFLICTED")
        return ContinuityState.COLLIDED, tuple(reasons)
    if len(row_slots) > 1:
        reasons.append("ROW_SLOT_SHIFT_DETECTED")
    if support_count < 2:
        reasons.append("LOW_TEMPORAL_SUPPORT")
        return ContinuityState.WEAK, tuple(reasons)
    return ContinuityState.STABLE, tuple(reasons)


def _derive_progression_state(
    sightings: tuple[tuple[str, int], ...],
) -> ContinuityProgressionState:
    if len(sightings) <= 1:
        return ContinuityProgressionState.STATIONARY

    deltas = []
    for (_, previous_slot), (_, current_slot) in zip(sightings, sightings[1:]):
        deltas.append(current_slot - previous_slot)

    non_zero = [delta for delta in deltas if delta != 0]
    if not non_zero:
        return ContinuityProgressionState.STATIONARY
    if all(delta > 0 for delta in non_zero):
        return ContinuityProgressionState.SLOT_INCREASE
    if all(delta < 0 for delta in non_zero):
        return ContinuityProgressionState.SLOT_DECREASE
    return ContinuityProgressionState.MIXED


def _identity_similarity(record: ContinuityRecord) -> float:
    identity_fields = (
        FieldKind.ITEM_NAME,
        FieldKind.ITEM_TYPE,
        FieldKind.ITEM_RARITY,
        FieldKind.ITEM_COUNT,
    )
    populated = sum(1 for field in identity_fields if record.fields.get(field, "").strip())
    return populated / len(identity_fields)


def _apply_overlap_progression(
    record: ContinuityRecord,
    overlap_pairs: dict[tuple[str, int, str, int], float],
) -> ContinuityRecord:
    if len(record.sightings) <= 1:
        return record

    transitions = [
        (frame_a_id, row_slot_a, frame_b_id, row_slot_b)
        for (frame_a_id, row_slot_a), (frame_b_id, row_slot_b) in zip(record.sightings, record.sightings[1:])
    ]
    if transitions and all(
        overlap_pairs.get(transition, 0.0) >= MIN_STRONG_OVERLAP_CONFIDENCE
        for transition in transitions
    ):
        reasons = tuple(reason for reason in record.reasons if reason != "ROW_SLOT_SHIFT_DETECTED")
        if "FRAME_OVERLAP_CONFIRMED" not in reasons:
            reasons = reasons + ("FRAME_OVERLAP_CONFIRMED",)
        return ContinuityRecord(
            continuity_key=record.continuity_key,
            profile_id=record.profile_id,
            row_slots=record.row_slots,
            state=record.state,
            progression_state=ContinuityProgressionState.STATIONARY,
            support_count=record.support_count,
            frame_ids=record.frame_ids,
            source_record_count=record.source_record_count,
            sightings=record.sightings,
            fields=record.fields,
            field_provenance=record.field_provenance,
            reasons=reasons,
        )
    return record
