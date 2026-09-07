from __future__ import annotations

from collections import defaultdict
import re

from .defiance_policy import load_defiance_policy, validate_candidate
from .models import CandidateDecision, CandidateStatus, FieldCandidate, FieldKind, RankedFieldCandidate


def rank_field_candidates(
    candidates: tuple[FieldCandidate, ...],
    *,
    profile_id: str,
) -> tuple[RankedFieldCandidate, ...]:
    if profile_id != "defiance":
        return _rank_without_policy(candidates)

    policy = load_defiance_policy()
    grouped: dict[tuple[str, FieldKind], list[RankedFieldCandidate]] = defaultdict(list)

    for candidate in candidates:
        grouped[(candidate.row_id, candidate.field_kind)].append(
            _candidate_to_ranked(candidate, policy=policy)
        )

    ranked_results: list[RankedFieldCandidate] = []
    for _, options in grouped.items():
        ranked_results.extend(_select_best(options))
    return tuple(ranked_results)


def _rank_without_policy(candidates: tuple[FieldCandidate, ...]) -> tuple[RankedFieldCandidate, ...]:
    grouped: dict[tuple[str, FieldKind], list[RankedFieldCandidate]] = defaultdict(list)
    for candidate in candidates:
        decision = CandidateDecision.SECONDARY
        if candidate.status is CandidateStatus.REJECTED:
            decision = CandidateDecision.REJECTED
        elif candidate.status is CandidateStatus.UNAVAILABLE:
            decision = CandidateDecision.UNAVAILABLE
        grouped[(candidate.row_id, candidate.field_kind)].append(
            RankedFieldCandidate(
                row_id=candidate.row_id,
                field_kind=candidate.field_kind,
                candidate_value=candidate.candidate_value,
                source_crop_id=candidate.crop_id,
                source_variant=candidate.source_variant,
                source_engine=candidate.source_engine,
                decision=decision,
                confidence=candidate.confidence,
                reasons=candidate.reasons,
            )
        )
    ranked_results: list[RankedFieldCandidate] = []
    for _, options in grouped.items():
        ranked_results.extend(_select_best(options))
    return tuple(ranked_results)


def _candidate_to_ranked(candidate: FieldCandidate, *, policy) -> RankedFieldCandidate:
    if candidate.status is CandidateStatus.UNAVAILABLE:
        return RankedFieldCandidate(
            row_id=candidate.row_id,
            field_kind=candidate.field_kind,
            candidate_value=candidate.candidate_value,
            source_crop_id=candidate.crop_id,
            source_variant=candidate.source_variant,
            source_engine=candidate.source_engine,
            decision=CandidateDecision.UNAVAILABLE,
            confidence=0.0,
            reasons=candidate.reasons,
        )

    valid, policy_reasons = validate_candidate(candidate.field_kind, candidate.candidate_value, policy=policy)
    if candidate.status is CandidateStatus.REJECTED or not valid:
        return RankedFieldCandidate(
            row_id=candidate.row_id,
            field_kind=candidate.field_kind,
            candidate_value=candidate.candidate_value,
            source_crop_id=candidate.crop_id,
            source_variant=candidate.source_variant,
            source_engine=candidate.source_engine,
            decision=CandidateDecision.REJECTED,
            confidence=0.0 if not valid else candidate.confidence,
            reasons=candidate.reasons + policy_reasons,
        )

    return RankedFieldCandidate(
        row_id=candidate.row_id,
        field_kind=candidate.field_kind,
        candidate_value=candidate.candidate_value,
        source_crop_id=candidate.crop_id,
        source_variant=candidate.source_variant,
        source_engine=candidate.source_engine,
        decision=CandidateDecision.SECONDARY,
        confidence=candidate.confidence,
        reasons=candidate.reasons + policy_reasons,
    )


def _select_best(options: list[RankedFieldCandidate]) -> list[RankedFieldCandidate]:
    valid = [option for option in options if option.decision is CandidateDecision.SECONDARY]
    if valid:
        best = sorted(valid, key=_rank_sort_key)[0]
        selected: list[RankedFieldCandidate] = []
        for option in options:
            if option.source_crop_id == best.source_crop_id:
                selected.append(
                    RankedFieldCandidate(
                        row_id=option.row_id,
                        field_kind=option.field_kind,
                        candidate_value=option.candidate_value,
                        source_crop_id=option.source_crop_id,
                        source_variant=option.source_variant,
                        source_engine=option.source_engine,
                        decision=CandidateDecision.SELECTED,
                        confidence=option.confidence,
                        reasons=option.reasons,
                    )
                )
            else:
                selected.append(option)
        return selected
    return options


def _rank_sort_key(option: RankedFieldCandidate) -> tuple[float, str]:
    score = float(option.confidence)
    if option.field_kind is FieldKind.ITEM_NAME:
        score += _item_name_observation_quality(option.candidate_value)
    return (-score, option.source_variant.value)


def _item_name_observation_quality(value: str) -> float:
    text = " ".join(str(value).split()).strip()
    if not text:
        return -1.0
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    score = 0.0
    if len(tokens) >= 2:
        score += 0.02
    if len(tokens) >= 3:
        score += 0.02
    if re.search(r"\b[IVX]{1,5}\b\s+ARK\b", text):
        score += 0.08
    if re.search(r"\b[IVX]{1,5}\s*ARK\b", text) and not re.search(r"\b[IVX]{1,5}\b\s+ARK\b", text):
        score -= 0.08
    glued_mixed_case = sum(1 for token in tokens if re.search(r"[a-z][A-Z]", token))
    score -= 0.06 * glued_mixed_case
    single_character_noise = sum(1 for token in tokens if len(token) == 1 and not re.fullmatch(r"[IVX]", token))
    score -= 0.04 * single_character_noise
    score += min(0.04, sum(len(token) for token in tokens) / 1000.0)
    return score
