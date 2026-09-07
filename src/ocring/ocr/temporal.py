from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import re

from .models import CandidateDecision, FieldKind, RankedFieldCandidate, TemporalFieldAggregate, TemporalSupportState
from .text_quality import FrameTextObservation, assess_item_name_text_quality


def merge_ranked_candidates(
    candidates: tuple[RankedFieldCandidate, ...],
    *,
    allow_slot_reuse: bool = False,
) -> tuple[TemporalFieldAggregate, ...]:
    grouped: dict[tuple[int, object, str], list[RankedFieldCandidate]] = defaultdict(list)
    item_name_candidates: dict[int, list[RankedFieldCandidate]] = defaultdict(list)
    grouped_reasons: dict[tuple[int, object, str], tuple[str, ...]] = {}
    # Populated only for row_ids that went through the item-name collapse below.
    # Holds every preprocess-variant crop id for that single frame/row observation,
    # so provenance is preserved even though it counts as one observation.
    collapsed_crop_ids_by_row_id: dict[str, tuple[str, ...]] = {}
    # Same idea, but the raw variant *text* readings (winner first) for that
    # row_id, used only for the text-quality gate below — never for clustering
    # or for support/independent-support counting.
    variant_values_by_row_id: dict[str, tuple[str, ...]] = {}

    for candidate in candidates:
        if candidate.decision not in {CandidateDecision.SELECTED, CandidateDecision.SECONDARY}:
            continue
        row_slot = _row_slot(candidate.row_id)
        if candidate.field_kind is FieldKind.ITEM_NAME:
            item_name_candidates[row_slot].append(candidate)
            continue
        key = (row_slot, candidate.field_kind, candidate.candidate_value)
        grouped[key].append(candidate)

    for row_slot, options in item_name_candidates.items():
        options, row_crop_ids, row_variant_values = _collapse_same_frame_item_name_variants(options)
        collapsed_crop_ids_by_row_id.update(row_crop_ids)
        variant_values_by_row_id.update(row_variant_values)
        for representative, cluster_options, cluster_reasons in _cluster_item_name_observations(options):
            key = (row_slot, FieldKind.ITEM_NAME, representative)
            grouped[key].extend(cluster_options)
            if cluster_reasons:
                grouped_reasons[key] = cluster_reasons

    aggregates: list[TemporalFieldAggregate] = []
    by_slot_field: dict[tuple[int, object], list[TemporalFieldAggregate]] = defaultdict(list)

    for (row_slot, field_kind, candidate_value), options in grouped.items():
        options = list(options)
        frame_ids = tuple(dict.fromkeys(_frame_id(option.row_id) for option in options))
        row_ids = tuple(dict.fromkeys(option.row_id for option in options))
        support_count = len(row_ids)
        # collapsed_crop_ids_by_row_id is keyed by row_id alone (frame+row), which is
        # shared across every field_kind on that row — only apply it for ITEM_NAME,
        # the field it was actually collapsed for, or it will leak item-name crop ids
        # into unrelated fields (item_rarity/item_type/item_synergy) on the same row.
        if field_kind is FieldKind.ITEM_NAME:
            crop_ids = tuple(
                dict.fromkeys(
                    crop_id
                    for option in options
                    for crop_id in collapsed_crop_ids_by_row_id.get(option.row_id, (option.source_crop_id,))
                )
            )
            variants_were_collapsed = any(
                len(collapsed_crop_ids_by_row_id.get(row_id, ())) > 1 for row_id in row_ids
            )
        else:
            crop_ids = tuple(dict.fromkeys(option.source_crop_id for option in options))
            variants_were_collapsed = False
        independent_support_count = len(frame_ids)
        reasons: list[str] = []
        if variants_were_collapsed:
            reasons.append("PREPROCESS_VARIANTS_COLLAPSED")
        if support_count > independent_support_count:
            reasons.append("CORRELATED_SAME_FRAME_SUPPORT")
        reasons.extend(grouped_reasons.get((row_slot, field_kind, candidate_value), ()))
        for option in options:
            reasons.extend(option.reasons)
        state = TemporalSupportState.SUPPORTED if independent_support_count >= 2 else TemporalSupportState.WEAK
        if field_kind is FieldKind.ITEM_NAME:
            # Text quality is an evidence-property gate layered on top of, not a
            # replacement for, temporal stability: it never changes `state`,
            # `support_count`, or `independent_support_count`.
            frame_observations = tuple(
                FrameTextObservation(
                    frame_id=_frame_id(option.row_id),
                    winner_value=option.candidate_value,
                    winner_confidence=option.confidence,
                    variant_values=variant_values_by_row_id.get(option.row_id, (option.candidate_value,)),
                )
                for option in options
            )
            text_quality = assess_item_name_text_quality(frame_observations)
        else:
            text_quality = None
        aggregate = TemporalFieldAggregate(
            temporal_key=f"{row_slot}:{field_kind.value}:{candidate_value}",
            row_slot=row_slot,
            field_kind=field_kind,
            candidate_value=candidate_value,
            support_state=state,
            support_count=support_count,
            independent_support_count=independent_support_count,
            best_confidence=max(option.confidence for option in options),
            contributing_frame_ids=frame_ids,
            contributing_row_ids=row_ids,
            contributing_crop_ids=crop_ids,
            reasons=tuple(dict.fromkeys(reasons)),
            text_quality_state=text_quality.state.value if text_quality else "",
            text_quality_score=text_quality.score if text_quality else 0.0,
            text_quality_reasons=text_quality.reasons if text_quality else (),
        )
        aggregates.append(aggregate)
        by_slot_field[(row_slot, field_kind)].append(aggregate)

    conflict_keys = {
        key
        for key, values in by_slot_field.items()
        if _has_temporal_value_conflict(key, values, allow_slot_reuse=allow_slot_reuse)
    }
    if conflict_keys:
        aggregates = [
            TemporalFieldAggregate(
                temporal_key=aggregate.temporal_key,
                row_slot=aggregate.row_slot,
                field_kind=aggregate.field_kind,
                candidate_value=aggregate.candidate_value,
                support_state=TemporalSupportState.CONFLICTED if (aggregate.row_slot, aggregate.field_kind) in conflict_keys else aggregate.support_state,
                support_count=aggregate.support_count,
                independent_support_count=aggregate.independent_support_count,
                best_confidence=aggregate.best_confidence,
                contributing_frame_ids=aggregate.contributing_frame_ids,
                contributing_row_ids=aggregate.contributing_row_ids,
                contributing_crop_ids=aggregate.contributing_crop_ids,
                reasons=("TEMPORAL_VALUE_CONFLICT",) + aggregate.reasons if (aggregate.row_slot, aggregate.field_kind) in conflict_keys else aggregate.reasons,
                text_quality_state=aggregate.text_quality_state,
                text_quality_score=aggregate.text_quality_score,
                text_quality_reasons=aggregate.text_quality_reasons,
            )
            for aggregate in aggregates
        ]

    return tuple(
        sorted(
            aggregates,
            key=lambda item: (item.row_slot, item.field_kind.value, -item.support_count, item.candidate_value),
        )
    )


def _has_temporal_value_conflict(
    key: tuple[int, object],
    values: list[TemporalFieldAggregate],
    *,
    allow_slot_reuse: bool,
) -> bool:
    if len(values) <= 1:
        return False
    _row_slot, field_kind = key
    if not allow_slot_reuse or field_kind is not FieldKind.ITEM_NAME:
        return True
    for index, left in enumerate(values):
        left_frames = set(left.contributing_frame_ids)
        for right in values[index + 1 :]:
            # Same-frame disagreement is still a real conflict. Different items
            # seen in the same screen slot at different times are slot reuse.
            if left_frames.intersection(right.contributing_frame_ids):
                return True
    return False


def _row_slot(row_id: str) -> int:
    try:
        return int(row_id.rsplit(":", 1)[-1])
    except ValueError:
        return 0


def _frame_id(row_id: str) -> str:
    return row_id.split(":row:", 1)[0]


def _cluster_item_name_observations(
    options: list[RankedFieldCandidate],
) -> tuple[tuple[str, tuple[RankedFieldCandidate, ...], tuple[str, ...]], ...]:
    clusters: list[list[RankedFieldCandidate]] = []
    for option in options:
        for cluster in clusters:
            if _same_observed_item_identity(option.candidate_value, cluster[0].candidate_value):
                cluster.append(option)
                break
        else:
            clusters.append([option])

    results: list[tuple[str, tuple[RankedFieldCandidate, ...], tuple[str, ...]]] = []
    for cluster in clusters:
        representative = _representative_observed_item_name(cluster)
        reasons = ("OBSERVED_IDENTITY_CLUSTERED",) if len({item.candidate_value for item in cluster}) > 1 else ()
        results.append((representative, tuple(cluster), reasons))
    return tuple(results)


def _collapse_same_frame_item_name_variants(
    options: list[RankedFieldCandidate],
) -> tuple[list[RankedFieldCandidate], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Reduce a single frame/row's multiple preprocess-variant candidates to one.

    A single observation (one frame, one row) can produce several ITEM_NAME
    candidates — one per preprocess variant (high_contrast/sharpened/grayscale).
    Those must count as exactly one independent observation, and must never be
    allowed to land in two different identity clusters (that would let one
    frame's OCR noise masquerade as two temporally-disjoint "slot reuse"
    observations and defeat allow_recorded_slot_reuse's conflict exemption).
    The losing variants' crop ids and raw text are preserved (not discarded) so
    the merged observation's provenance still shows every variant that was
    examined, and so a later evidence-quality assessment can see whether the
    variants agreed with each other — without those variants ever being
    reintroduced as extra independent/support observations.
    """
    by_row_id: dict[str, list[RankedFieldCandidate]] = defaultdict(list)
    for option in options:
        by_row_id[option.row_id].append(option)
    collapsed: list[RankedFieldCandidate] = []
    crop_ids_by_row_id: dict[str, tuple[str, ...]] = {}
    variant_values_by_row_id: dict[str, tuple[str, ...]] = {}
    for row_id, row_options in by_row_id.items():
        winner = sorted(
            row_options,
            key=lambda option: (
                _decision_rank(option.decision),
                option.confidence,
                _representative_text_quality(option.candidate_value),
                option.candidate_value,
            ),
            reverse=True,
        )[0]
        collapsed.append(winner)
        losers = [option for option in row_options if option is not winner]
        crop_ids_by_row_id[row_id] = tuple(
            dict.fromkeys([winner.source_crop_id] + [option.source_crop_id for option in losers])
        )
        variant_values_by_row_id[row_id] = tuple([winner.candidate_value] + [option.candidate_value for option in losers])
    return collapsed, crop_ids_by_row_id, variant_values_by_row_id


def _decision_rank(decision: CandidateDecision) -> int:
    if decision is CandidateDecision.SELECTED:
        return 2
    if decision is CandidateDecision.SECONDARY:
        return 1
    return 0


def _same_observed_item_identity(left: str, right: str) -> bool:
    left_tokens = _identity_tokens(left)
    right_tokens = _identity_tokens(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False
    if len(left_tokens) != len(right_tokens):
        return False
    if _roman_suffix(left_tokens) != _roman_suffix(right_tokens):
        return False
    joined_left = " ".join(left_tokens)
    joined_right = " ".join(right_tokens)
    if SequenceMatcher(None, joined_left, joined_right).ratio() < 0.91:
        return False
    for left_token, right_token in zip(left_tokens, right_tokens):
        if left_token == right_token:
            continue
        ratio = SequenceMatcher(None, left_token, right_token).ratio()
        if len(left_token) >= 4 and len(right_token) >= 4 and ratio < 0.86:
            return False
        if len(left_token) < 4 or len(right_token) < 4:
            if ratio < 0.80:
                return False
    return True


def _identity_tokens(value: str) -> tuple[str, ...]:
    cleaned = re.sub(r"(?<=[A-Za-z])(?=[IVX]{1,4}$)", " ", value.strip())
    cleaned = re.sub(r"[^A-Za-z0-9IVXivx]+", " ", cleaned)
    tokens = [token.lower() for token in cleaned.split()]
    while tokens and (len(tokens[0]) == 1 or tokens[0].isdigit()):
        tokens.pop(0)
    return tuple(tokens)


def _roman_suffix(tokens: tuple[str, ...]) -> str:
    if tokens and re.fullmatch(r"[ivx]{1,4}", tokens[-1]):
        return tokens[-1]
    return ""


def _representative_observed_item_name(cluster: list[RankedFieldCandidate]) -> str:
    by_value: dict[str, list[RankedFieldCandidate]] = defaultdict(list)
    for option in cluster:
        by_value[option.candidate_value].append(option)
    return sorted(
        by_value.items(),
        key=lambda item: (
            len({_frame_id(option.row_id) for option in item[1]}),
            len(item[1]),
            _representative_text_quality(item[0]),
            max(option.confidence for option in item[1]),
            item[0],
        ),
        reverse=True,
    )[0][0]


def _representative_text_quality(value: str) -> float:
    tokens = _identity_tokens(value)
    if not tokens:
        return -1.0
    score = 0.0
    if value[:1].isalnum():
        score += 0.2
    if _roman_suffix(tokens):
        score += 0.25
    if any(not token.isascii() for token in value):
        score -= 0.4
    if len(tokens) >= 3:
        score += 0.15
    return score
