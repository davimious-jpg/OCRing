from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .defiance_semantic import DefianceSemantic
from .inventory_definition_engine import InventoryDefinitionEngine
from .models import (
    AssembledCandidateRecord,
    FieldKind,
    FrameOverlap,
    RecordAssemblyState,
    TemporalFieldAggregate,
    TemporalSupportState,
)
from .truth_state import TruthState


REQUIRED_FIELDS = (
    FieldKind.ITEM_NAME,
    FieldKind.ITEM_RARITY,
    FieldKind.ITEM_COUNT,
    FieldKind.ITEM_TYPE,
)

_FRAME_SEQUENCE_PATTERN = re.compile(r"(\d+)$")


def assemble_candidate_records(
    aggregates: tuple[TemporalFieldAggregate, ...],
    *,
    profile_id: str,
    profile_version: str = "",
    scan_timestamp: str = "",
    definition_engine: InventoryDefinitionEngine | None = None,
    temporal_identity_aware: bool = False,
) -> tuple[AssembledCandidateRecord, ...]:
    """Turn temporal field aggregates into final candidate records.

    By default (temporal_identity_aware=False - the live/single-screen path)
    this keeps exactly one record per row_slot, picking the single best
    aggregate per field. That is correct for a static screen, where a
    row_slot IS the item.

    For a recorded scrolling extraction (temporal_identity_aware=True), a
    row_slot is only an observation coordinate: over the course of a scroll it
    can host many different, temporally distinct real items one after
    another. This mode splits each row_slot's SUPPORTED item_name aggregates
    into temporally distinct identities (an "epoch" - a contiguous run of a
    row_slot's own contributing frames with no other item_name observation
    interleaved) and emits one record per identity, instead of collapsing the
    whole row_slot's history into a single winner.
    """
    grouped: dict[int, list[TemporalFieldAggregate]] = defaultdict(list)
    for aggregate in aggregates:
        grouped[aggregate.row_slot].append(aggregate)

    records: list[AssembledCandidateRecord] = []
    for row_slot, options in sorted(grouped.items()):
        for unit in _temporal_identity_units(row_slot, options, temporal_identity_aware=temporal_identity_aware):
            records.append(
                _assemble_one_record(
                    row_slot=row_slot,
                    temporal_identity_id=unit.temporal_identity_id,
                    fields_by_kind=unit.fields_by_kind,
                    not_visible_fields=unit.not_visible_fields,
                    profile_id=profile_id,
                    profile_version=profile_version,
                    scan_timestamp=scan_timestamp,
                    definition_engine=definition_engine,
                )
            )

    return tuple(records)


@dataclass(frozen=True)
class _AssemblyUnit:
    temporal_identity_id: str
    fields_by_kind: dict[FieldKind, list[TemporalFieldAggregate]]
    not_visible_fields: tuple[FieldKind, ...] = ()


@dataclass(frozen=True)
class _TemporalEpoch:
    source: TemporalFieldAggregate
    frame_sequences: tuple[int, ...]
    frame_ids: tuple[str, ...]
    row_ids: tuple[str, ...]
    is_full_span: bool

    @property
    def min_sequence(self) -> int:
        return self.frame_sequences[0]

    @property
    def max_sequence(self) -> int:
        return self.frame_sequences[-1]

    def as_aggregate(self) -> TemporalFieldAggregate:
        if self.is_full_span:
            return self.source
        # A split-off epoch: independent_support_count/support_count are
        # recomputed exactly from this epoch's own frame subset (this is what
        # gates SUPPORTED/WEAK and auto-store eligibility, so it must be
        # exact). best_confidence, text-quality, and contributing_crop_ids are
        # necessarily inherited from the parent aggregate (temporal.py's
        # output does not retain a per-frame confidence/crop-id
        # breakdown once aggregated) - real, observed values from this same
        # identity cluster, never fabricated, just not perfectly re-scoped to
        # the sub-epoch (a split epoch's crop-id list may include a handful of
        # crops belonging to a chronologically disjoint sibling epoch).
        # Flagged via a reason so this is never silently treated as more
        # precise than it is.
        independent_support_count = len(self.frame_ids)
        support_count = len(self.row_ids)
        state = (
            TemporalSupportState.SUPPORTED
            if independent_support_count >= 2
            else TemporalSupportState.WEAK
        )
        return TemporalFieldAggregate(
            temporal_key=f"{self.source.temporal_key}:epoch:{self.min_sequence}-{self.max_sequence}",
            row_slot=self.source.row_slot,
            field_kind=self.source.field_kind,
            candidate_value=self.source.candidate_value,
            support_state=state,
            support_count=support_count,
            independent_support_count=independent_support_count,
            best_confidence=self.source.best_confidence,
            contributing_frame_ids=self.frame_ids,
            contributing_row_ids=self.row_ids,
            contributing_crop_ids=self.source.contributing_crop_ids,
            reasons=self.source.reasons + ("TEMPORAL_EPOCH_SPLIT_EVIDENCE_INHERITED",),
            text_quality_state=self.source.text_quality_state,
            text_quality_score=self.source.text_quality_score,
            text_quality_reasons=self.source.text_quality_reasons,
        )

    def identity_id(self) -> str:
        return f"{self.source.row_slot}:epoch:{self.min_sequence}-{self.max_sequence}"


def _temporal_identity_units(
    row_slot: int,
    options: list[TemporalFieldAggregate],
    *,
    temporal_identity_aware: bool,
) -> list[_AssemblyUnit]:
    if not temporal_identity_aware:
        by_field: dict[FieldKind, list[TemporalFieldAggregate]] = defaultdict(list)
        for option in options:
            by_field[option.field_kind].append(option)
        return [_AssemblyUnit(str(row_slot), dict(by_field))]

    item_name_options = [option for option in options if option.field_kind is FieldKind.ITEM_NAME]
    other_by_kind: dict[FieldKind, list[TemporalFieldAggregate]] = defaultdict(list)
    for option in options:
        if option.field_kind is not FieldKind.ITEM_NAME:
            other_by_kind[option.field_kind].append(option)

    epochs = _split_supported_item_name_epochs(item_name_options)
    if not epochs:
        # Nothing temporally stable at this slot at all - fall back to the
        # legacy single-record shape so the slot still surfaces as its usual
        # HOLD/UNKNOWN record instead of silently disappearing.
        by_field: dict[FieldKind, list[TemporalFieldAggregate]] = defaultdict(list)
        for option in options:
            by_field[option.field_kind].append(option)
        return [_AssemblyUnit(str(row_slot), dict(by_field))]

    units: list[_AssemblyUnit] = []
    for epoch in epochs:
        fields_by_kind: dict[FieldKind, list[TemporalFieldAggregate]] = {
            FieldKind.ITEM_NAME: [epoch.as_aggregate()],
        }
        not_visible: list[FieldKind] = []
        for field_kind, candidates in other_by_kind.items():
            overlapping = [
                candidate
                for candidate in candidates
                if _has_temporal_overlap(candidate, epoch.min_sequence, epoch.max_sequence)
            ]
            if overlapping:
                fields_by_kind[field_kind] = overlapping
            else:
                # This field has evidence somewhere at this row_slot, but none
                # of it falls inside this identity's own time window - never
                # borrow a neighboring epoch's (or a later/earlier slot
                # occupant's) value to complete the record.
                not_visible.append(field_kind)
        units.append(_AssemblyUnit(epoch.identity_id(), fields_by_kind, tuple(not_visible)))
    return units


def _split_supported_item_name_epochs(item_name_options: list[TemporalFieldAggregate]) -> list[_TemporalEpoch]:
    """Split each SUPPORTED item_name aggregate into temporally contiguous epochs.

    An aggregate's contributing frames are already grouped by text identity
    (temporal.py's fuzzy clustering) - not by chronology. If the exact same
    (or fuzzy-matching) text was observed at two very different times with a
    different real item interleaved between them at the same row_slot, that
    aggregate's contributing_frame_ids will contain a gap where another
    aggregate's frames fall in between. Splitting there turns "one row_slot,
    one final record" into "duplicate observations of the same physical
    passage stay one record; separate passages that happen to share a
    displayed name become two records" - using only the frame/row provenance
    the temporal layer already produced, never inventing a new identity
    concept.

    Only a SUPPORTED interloper (itself independently corroborated across
    >=2 frames) counts as proof of a passage break. A single WEAK/
    single-frame observation in between is exactly the kind of transient
    misread (motion blur, a half-scrolled frame) the reducer and temporal
    layer already treat as unreliable elsewhere in this pipeline; treating
    it as decisive evidence of a new physical passage would fragment one
    continuous, well-supported dwell into multiple records for no reason
    (confirmed against a real recorded session: a single garbled frame
    between two halves of one continuous item dwell was initially splitting
    it into two records before this restriction).
    """
    # Global per-slot timeline: every SUPPORTED item_name candidate's own
    # frame sequence, tagged with which source aggregate it belongs to, so a
    # SUPPORTED aggregate's own gaps can be checked against every OTHER
    # SUPPORTED aggregate observed for this same row_slot.
    timeline: list[tuple[int, int]] = []
    for index, option in enumerate(item_name_options):
        if option.support_state is not TemporalSupportState.SUPPORTED:
            continue
        for frame_id in option.contributing_frame_ids:
            sequence = _frame_sequence_number(frame_id)
            if sequence is not None:
                timeline.append((sequence, index))
    timeline.sort()

    epochs: list[_TemporalEpoch] = []
    for index, option in enumerate(item_name_options):
        if option.support_state is not TemporalSupportState.SUPPORTED:
            continue
        by_sequence: dict[int, tuple[str, str]] = {}
        for frame_id, row_id in zip(option.contributing_frame_ids, option.contributing_row_ids):
            sequence = _frame_sequence_number(frame_id)
            if sequence is not None:
                by_sequence[sequence] = (frame_id, row_id)
        sequences = sorted(by_sequence)
        if not sequences:
            continue

        runs: list[list[int]] = [[sequences[0]]]
        for previous, current in zip(sequences, sequences[1:]):
            interloper = any(
                owner != index and previous < sequence < current
                for sequence, owner in timeline
            )
            if interloper:
                runs.append([current])
            else:
                runs[-1].append(current)

        is_full_span = len(runs) == 1
        for run in runs:
            frame_ids = tuple(by_sequence[sequence][0] for sequence in run)
            row_ids = tuple(by_sequence[sequence][1] for sequence in run)
            epochs.append(
                _TemporalEpoch(
                    source=option,
                    frame_sequences=tuple(run),
                    frame_ids=frame_ids,
                    row_ids=row_ids,
                    is_full_span=is_full_span,
                )
            )
    return epochs


def _has_temporal_overlap(candidate: TemporalFieldAggregate, min_sequence: int, max_sequence: int) -> bool:
    for frame_id in candidate.contributing_frame_ids:
        sequence = _frame_sequence_number(frame_id)
        if sequence is not None and min_sequence <= sequence <= max_sequence:
            return True
    return False


def _frame_sequence_number(frame_id: str) -> int | None:
    match = _FRAME_SEQUENCE_PATTERN.search(frame_id)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _assemble_one_record(
    *,
    row_slot: int,
    temporal_identity_id: str,
    fields_by_kind: dict[FieldKind, list[TemporalFieldAggregate]],
    not_visible_fields: tuple[FieldKind, ...] = (),
    profile_id: str,
    profile_version: str,
    scan_timestamp: str,
    definition_engine: InventoryDefinitionEngine | None,
) -> AssembledCandidateRecord:
    selected_fields: dict[FieldKind, TemporalFieldAggregate] = {}
    reasons: list[str] = []

    for field_kind, field_options in fields_by_kind.items():
        best = _pick_best_aggregate(field_options)
        selected_fields[field_kind] = best
        if field_kind is FieldKind.ITEM_NAME and not _is_stable_identity(field_kind, best):
            reasons.append("ITEM_NAME_UNRESOLVED_IDENTITY")
        if any(option.support_state is TemporalSupportState.CONFLICTED for option in field_options):
            reasons.append(f"{field_kind.value.upper()}_TEMPORAL_CONFLICT")
    for field_kind in not_visible_fields:
        reasons.append(f"{field_kind.value.upper()}_FIELD_NOT_VISIBLE_FOR_THIS_IDENTITY")

    fields = {
        field_kind: _resolved_field_value(field_kind, aggregate)
        for field_kind, aggregate in selected_fields.items()
    }
    definition_used = (
        definition_engine.determine_record_class({field.value: value for field, value in fields.items()})
        if definition_engine is not None
        else "Weapon"
    )
    required_fields = _required_fields_for_definition(definition_engine, definition_used)
    missing_fields = tuple(field for field in required_fields if field not in selected_fields or not fields.get(field))
    if missing_fields:
        reasons.extend(f"{field.value.upper()}_MISSING" for field in missing_fields)

    state = _derive_record_state(selected_fields, missing_fields)
    support_summary = {
        field_kind.value: {
            "support_state": aggregate.support_state.value,
            "support_count": aggregate.support_count,
            "independent_support_count": aggregate.independent_support_count,
            "best_confidence": aggregate.best_confidence,
            "frame_hint": aggregate.contributing_frame_ids[0] if aggregate.contributing_frame_ids else "",
            "source_frame_ids": aggregate.contributing_frame_ids,
            "source_row_ids": aggregate.contributing_row_ids,
            "source_crop_ids": aggregate.contributing_crop_ids,
            "text_quality_state": aggregate.text_quality_state,
            "text_quality_score": aggregate.text_quality_score,
            "text_quality_reasons": aggregate.text_quality_reasons,
        }
        for field_kind, aggregate in selected_fields.items()
    }
    field_details = {
        field_kind.value: {
            "field_confidence": aggregate.best_confidence,
            "source_text": _resolved_field_value(field_kind, aggregate),
            "raw_observation": aggregate.candidate_value,
            "status": _field_detail_status(field_kind, aggregate),
            "identity_status": _identity_status(field_kind, aggregate),
            "reference_status": _reference_status(aggregate),
            "direct_observation": _is_stable_identity(field_kind, aggregate),
            "text_quality_state": aggregate.text_quality_state,
            "text_quality_score": aggregate.text_quality_score,
            "text_quality_reasons": aggregate.text_quality_reasons,
        }
        for field_kind, aggregate in selected_fields.items()
    }
    for field_kind in not_visible_fields:
        # Real evidence exists for this field somewhere at this row_slot, but
        # none of it falls inside this identity's own temporal window - never
        # borrowed from a neighboring identity or a different slot occupant.
        field_details[field_kind.value] = {
            "field_confidence": 0.0,
            "source_text": "",
            "raw_observation": "",
            "status": "FIELD_NOT_VISIBLE",
            "identity_status": "UNKNOWN",
            "reference_status": "REFERENCE_DATA_MISSING",
            "direct_observation": False,
            "text_quality_state": "",
            "text_quality_score": 0.0,
            "text_quality_reasons": (),
        }

    frame_rank = _frame_rank_map(tuple(selected_fields.values()))
    source_frame_ids = tuple(
        sorted(
            dict.fromkeys(
                frame_id
                for aggregate in selected_fields.values()
                for frame_id in aggregate.contributing_frame_ids
            ),
            key=lambda frame_id: (frame_rank.get(frame_id, 10_000), frame_id),
        )
    )
    source_row_ids = tuple(
        sorted(
            dict.fromkeys(
                row_id
                for aggregate in selected_fields.values()
                for row_id in aggregate.contributing_row_ids
            ),
            key=lambda row_id: _row_id_sort_key(row_id, frame_rank),
        )
    )

    return AssembledCandidateRecord(
        row_slot=row_slot,
        profile_id=profile_id,
        state=state,
        fields=fields,
        support_summary=support_summary,
        source_frame_ids=source_frame_ids,
        source_row_ids=source_row_ids,
        missing_fields=missing_fields,
        overlap_provenance={},
        reasons=tuple(dict.fromkeys(reasons)),
        truth_state=TruthState.RECOGNIZED.value if fields else TruthState.OBSERVED.value,
        progression_reason="FIELDS_RECOGNIZED_FROM_TEMPORAL_EVIDENCE" if fields else "SCREEN_OBSERVED",
        profile_version=profile_version,
        scan_timestamp=scan_timestamp,
        definition_used=definition_used,
        field_details=field_details,
        semantic_notes=(),
        temporal_identity_id=temporal_identity_id,
    )


def apply_overlap_provenance(
    records: tuple[AssembledCandidateRecord, ...],
    overlaps: tuple[FrameOverlap, ...],
) -> tuple[AssembledCandidateRecord, ...]:
    annotated: list[AssembledCandidateRecord] = []
    for record in records:
        matched: list[dict[str, object]] = []
        row_lookup = set(record.source_row_ids)
        for overlap in overlaps:
            for row_slot_a, row_slot_b in overlap.overlap_rows:
                row_a = f"{overlap.frame_a_id}:row:{row_slot_a}"
                row_b = f"{overlap.frame_b_id}:row:{row_slot_b}"
                if row_a in row_lookup or row_b in row_lookup:
                    matched.append(
                        {
                            "frame_a_id": overlap.frame_a_id,
                            "frame_b_id": overlap.frame_b_id,
                            "row_slot_a": row_slot_a,
                            "row_slot_b": row_slot_b,
                            "overlap_confidence": overlap.overlap_confidence,
                        }
                    )
        overlap_provenance = dict(record.overlap_provenance)
        if matched:
            overlap_provenance["overlaps"] = tuple(matched)
        annotated.append(
            AssembledCandidateRecord(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=record.state,
                fields=record.fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=record.missing_fields,
                overlap_provenance=overlap_provenance,
                reasons=record.reasons,
                truth_state=record.truth_state,
                progression_reason=record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=record.definition_used,
                field_details=record.field_details,
                semantic_notes=record.semantic_notes,
                temporal_identity_id=record.temporal_identity_id,
            )
        )
    return tuple(annotated)


def apply_semantic_provenance(
    records: tuple[AssembledCandidateRecord, ...],
    *,
    reconstruction_results: dict[str, dict[str, object]],
    allocation_results: dict[str, dict[str, object]],
) -> tuple[AssembledCandidateRecord, ...]:
    enriched: list[AssembledCandidateRecord] = []
    for record in records:
        identity_key = _identity_key(record)
        reconstruction = reconstruction_results.get(identity_key, {})
        allocation = allocation_results.get(identity_key, {})
        reasons = list(record.reasons)
        if reconstruction.get("status") == "NEEDS_REVIEW":
            reasons.append("AI_RECONSTRUCTION_NEEDS_REVIEW")
        if allocation.get("status") == "NEEDS_REVIEW":
            reasons.append("SEMANTIC_ALLOCATION_NEEDS_REVIEW")
        overlap_provenance = dict(record.overlap_provenance)
        overlap_provenance["reconstruction_provenance"] = reconstruction
        overlap_provenance["allocation_provenance"] = allocation
        enriched.append(
            AssembledCandidateRecord(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=record.state,
                fields=record.fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=record.missing_fields,
                overlap_provenance=overlap_provenance,
                reasons=tuple(dict.fromkeys(reasons)),
                truth_state=record.truth_state,
                progression_reason=record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=record.definition_used,
                field_details=record.field_details,
                semantic_notes=record.semantic_notes,
                temporal_identity_id=record.temporal_identity_id,
            )
        )
    return tuple(enriched)


def merge_allocation_fields(
    records: tuple[AssembledCandidateRecord, ...],
    allocation_results: dict[str, dict[str, object]],
) -> tuple[AssembledCandidateRecord, ...]:
    enriched: list[AssembledCandidateRecord] = []
    for record in records:
        allocation = allocation_results.get(_identity_key(record), {})
        field_values = {
            str(key): str(value)
            for key, value in dict(allocation.get("field_values", {})).items()
            if str(value).strip()
        }
        merged_fields = dict(record.fields)
        for field_name, value in field_values.items():
            field_kind = _field_kind_from_name(field_name)
            if field_kind is None:
                continue
            if not merged_fields.get(field_kind):
                merged_fields[field_kind] = value
        if not merged_fields.get(FieldKind.ITEM_TYPE):
            mod_slot = field_values.get("mod_slot", "")
            if mod_slot:
                merged_fields[FieldKind.ITEM_TYPE] = mod_slot
                field_values.setdefault(FieldKind.ITEM_TYPE.value, mod_slot)

        field_details = dict(record.field_details)
        allocation_confidence = float(allocation.get("confidence") or 0.0)
        for field_name, value in field_values.items():
            details = dict(field_details.get(field_name, {}))
            details.setdefault("field_confidence", allocation_confidence)
            details.setdefault("source_text", value)
            details["status"] = "ALLOCATED"
            details["allocation_source"] = "semantic_allocator"
            details["direct_observation"] = False
            field_details[field_name] = details

        missing_fields = tuple(field for field in REQUIRED_FIELDS if not merged_fields.get(field))
        state = record.state if record.state is RecordAssemblyState.CONFLICTED else _derive_record_state(
            {
                field_kind: aggregate
                for field_kind, aggregate in ()
            },
            missing_fields,
        )
        reasons = list(record.reasons)
        if field_values:
            reasons.append("SEMANTIC_ALLOCATION_ENRICHED")
        resolved_field_names = {field.value for field in REQUIRED_FIELDS if field not in missing_fields}
        reasons = [
            reason
            for reason in reasons
            if not (
                reason.endswith("_MISSING")
                and reason.removesuffix("_MISSING").lower() in resolved_field_names
            )
        ]

        enriched.append(
            AssembledCandidateRecord(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=state,
                fields=merged_fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=missing_fields,
                overlap_provenance=record.overlap_provenance,
                reasons=tuple(dict.fromkeys(reasons)),
                truth_state=record.truth_state,
                progression_reason=record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=record.definition_used,
                field_details=field_details,
                semantic_notes=record.semantic_notes,
                temporal_identity_id=record.temporal_identity_id,
            )
        )
    return tuple(enriched)


def apply_defiance_semantic_notes(
    records: tuple[AssembledCandidateRecord, ...],
    semantic: DefianceSemantic | None = None,
) -> tuple[AssembledCandidateRecord, ...]:
    semantic = semantic or DefianceSemantic.load()
    enriched: list[AssembledCandidateRecord] = []
    for record in records:
        notes = list(record.semantic_notes)

        rarity_value = record.fields.get(FieldKind.ITEM_RARITY, "")
        observed_color = _detail_value(record.field_details.get(FieldKind.ITEM_RARITY.value), "observed_color")
        if rarity_value and observed_color:
            conflict = semantic.detect_rarity_conflict(rarity_value, observed_color)
            if conflict is not None:
                notes.append(conflict.message)

        mod_slot = _detail_value(record.field_details.get("mod_slot"), "source_text")
        weapon_type = record.fields.get(FieldKind.ITEM_TYPE, "")
        if mod_slot and weapon_type:
            warning = semantic.detect_slot_compatibility_warning(mod_slot, weapon_type)
            if warning is not None:
                notes.append(warning.message)

        enriched.append(
            AssembledCandidateRecord(
                row_slot=record.row_slot,
                profile_id=record.profile_id,
                state=record.state,
                fields=record.fields,
                support_summary=record.support_summary,
                source_frame_ids=record.source_frame_ids,
                source_row_ids=record.source_row_ids,
                missing_fields=record.missing_fields,
                overlap_provenance=record.overlap_provenance,
                reasons=record.reasons,
                truth_state=record.truth_state,
                progression_reason=record.progression_reason,
                profile_version=record.profile_version,
                scan_timestamp=record.scan_timestamp,
                definition_used=record.definition_used,
                field_details=record.field_details,
                semantic_notes=tuple(dict.fromkeys(notes)),
                temporal_identity_id=record.temporal_identity_id,
            )
        )
    return tuple(enriched)


def _pick_best_aggregate(options: list[TemporalFieldAggregate]) -> TemporalFieldAggregate:
    return sorted(
        options,
        key=lambda option: (
            _support_rank(option.support_state),
            option.support_count,
            option.best_confidence,
            option.candidate_value,
        ),
        reverse=True,
    )[0]


def _resolved_field_value(field_kind: FieldKind, aggregate: TemporalFieldAggregate) -> str:
    if field_kind is FieldKind.ITEM_NAME and not _is_stable_identity(field_kind, aggregate):
        return "UNKNOWN"
    return aggregate.candidate_value


def _field_detail_status(field_kind: FieldKind, aggregate: TemporalFieldAggregate) -> str:
    if not aggregate.candidate_value:
        return "UNKNOWN"
    if field_kind is FieldKind.ITEM_NAME and not _is_stable_identity(field_kind, aggregate):
        return "UNRESOLVED_IDENTITY"
    if field_kind is FieldKind.ITEM_NAME:
        return "OBSERVED_STABLE"
    return "OBSERVED"


def _identity_status(field_kind: FieldKind, aggregate: TemporalFieldAggregate) -> str:
    if not aggregate.candidate_value:
        return "UNKNOWN"
    if field_kind is not FieldKind.ITEM_NAME:
        return "OBSERVED"
    if _is_stable_identity(field_kind, aggregate):
        return "OBSERVED_STABLE"
    if aggregate.support_state is TemporalSupportState.CONFLICTED:
        return "OBSERVED_UNSTABLE"
    return "UNKNOWN"


def _reference_status(aggregate: TemporalFieldAggregate) -> str:
    if "REFERENCE_DATA_MISSING" in aggregate.reasons:
        return "REFERENCE_DATA_MISSING"
    return "REFERENCE_VERIFIED"


def _is_stable_identity(field_kind: FieldKind, aggregate: TemporalFieldAggregate) -> bool:
    if field_kind is not FieldKind.ITEM_NAME:
        return bool(aggregate.candidate_value)
    return (
        bool(aggregate.candidate_value)
        and aggregate.support_state is TemporalSupportState.SUPPORTED
        and aggregate.independent_support_count >= 2
    )


def _support_rank(state: TemporalSupportState) -> int:
    if state is TemporalSupportState.SUPPORTED:
        return 3
    if state is TemporalSupportState.WEAK:
        return 2
    return 1


def _derive_record_state(
    selected_fields: dict[FieldKind, TemporalFieldAggregate],
    missing_fields: tuple[FieldKind, ...],
) -> RecordAssemblyState:
    if any(aggregate.support_state is TemporalSupportState.CONFLICTED for aggregate in selected_fields.values()):
        return RecordAssemblyState.CONFLICTED
    if missing_fields:
        return RecordAssemblyState.PARTIAL
    return RecordAssemblyState.COMPLETE


def _required_fields_for_definition(
    definition_engine: InventoryDefinitionEngine | None,
    definition_used: str,
) -> tuple[FieldKind, ...]:
    if definition_engine is None:
        return REQUIRED_FIELDS
    try:
        required = definition_engine.get_required_fields(definition_used)
    except KeyError:
        return REQUIRED_FIELDS
    resolved: list[FieldKind] = []
    for field_name in required:
        field_kind = _field_kind_from_name(field_name)
        if field_kind is not None:
            resolved.append(field_kind)
    return tuple(resolved) or REQUIRED_FIELDS


def _frame_rank_map(aggregates: tuple[TemporalFieldAggregate, ...]) -> dict[str, int]:
    rank: dict[str, int] = {}
    next_rank = 0
    for aggregate in aggregates:
        for frame_id in aggregate.contributing_frame_ids:
            if frame_id not in rank:
                rank[frame_id] = next_rank
                next_rank += 1
    return rank


def _row_id_sort_key(row_id: str, frame_rank: dict[str, int]) -> tuple[int, int, str]:
    parts = row_id.split(":row:")
    frame_id = parts[0]
    row_slot = 10_000
    if len(parts) == 2:
        try:
            row_slot = int(parts[1])
        except ValueError:
            row_slot = 10_000
    return (frame_rank.get(frame_id, 10_000), row_slot, row_id)


def _identity_key(record: AssembledCandidateRecord) -> str:
    return str(record.temporal_identity_id or record.row_slot)


def _field_kind_from_name(field_name: str) -> FieldKind | None:
    for field_kind in FieldKind:
        if field_kind.value == field_name:
            return field_kind
    return None


def _detail_value(detail: object, key: str) -> str:
    if isinstance(detail, dict):
        value = detail.get(key, "")
        return str(value).strip() if value is not None else ""
    if key == "source_text" and detail is not None:
        return str(detail).strip()
    return ""
