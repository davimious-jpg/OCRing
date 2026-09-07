from __future__ import annotations

import re

from .models import CandidateStatus, FieldCandidate, FieldKind, OcrAttempt


def build_field_candidates(
    attempts: tuple[OcrAttempt, ...],
    *,
    profile_id: str,
) -> tuple[FieldCandidate, ...]:
    del profile_id
    return tuple(_attempt_to_candidate(attempt) for attempt in attempts)


def _attempt_to_candidate(attempt: OcrAttempt) -> FieldCandidate:
    if attempt.status.value != "ok":
        return FieldCandidate(
            crop_id=attempt.crop_id,
            row_id=attempt.row_id,
            field_kind=attempt.field_kind,
            candidate_value="",
            source_variant=attempt.variant,
            source_engine=attempt.engine_name,
            status=CandidateStatus.UNAVAILABLE,
            confidence=0.0,
            reasons=attempt.reasons or ("OCR_NOT_AVAILABLE",),
        )

    normalized_value, reasons = _normalize_field_value(attempt.field_kind, attempt.normalized_text)
    status = CandidateStatus.CANDIDATE if normalized_value else CandidateStatus.REJECTED
    confidence = attempt.confidence if normalized_value else 0.0
    if not normalized_value and not reasons:
        reasons = ("EMPTY_NORMALIZED_VALUE",)

    return FieldCandidate(
        crop_id=attempt.crop_id,
        row_id=attempt.row_id,
        field_kind=attempt.field_kind,
        candidate_value=normalized_value,
        source_variant=attempt.variant,
        source_engine=attempt.engine_name,
        status=status,
        confidence=confidence,
        reasons=reasons,
    )


def _normalize_field_value(field_kind: FieldKind, value: str) -> tuple[str, tuple[str, ...]]:
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return "", ()

    if field_kind is FieldKind.ITEM_COUNT:
        count = _normalize_count(cleaned)
        return count, ("COUNT_PARSE_REJECTED",) if not count else ()

    if field_kind is FieldKind.ITEM_RARITY:
        rarity = _normalize_rarity(cleaned)
        return rarity, ("RARITY_PARSE_REJECTED",) if not rarity else ()

    if field_kind is FieldKind.ITEM_SYNERGY:
        synergy = _normalize_synergy(cleaned)
        return synergy, ("TEXT_NORMALIZATION_REJECTED",) if not synergy else ()

    text = _normalize_text_field(cleaned)
    return text, () if text else ("TEXT_NORMALIZATION_REJECTED",)


def _normalize_text_field(value: str) -> str:
    repaired = value
    repaired = repaired.replace("0", "O") if any(ch.isalpha() for ch in repaired) else repaired
    repaired = repaired.replace("|", "I")
    repaired = re.sub(r"\s+", " ", repaired)
    repaired = repaired.strip(" -_:")
    return repaired


def _normalize_synergy(value: str) -> str:
    stripped = re.sub(r"^\s*synergy\s*[:\-]\s*", "", value, flags=re.IGNORECASE)
    return _normalize_text_field(stripped)


def _normalize_count(value: str) -> str:
    compact = value.lower().replace(" ", "")
    compact = compact.replace("x", "")
    digits = "".join(ch for ch in compact if ch.isdigit())
    return digits


def _normalize_rarity(value: str) -> str:
    normalized = value.upper().replace(" ", "")
    numeral_aliases = {
        "I": "Tier I",
        "II": "Tier II",
        "III": "Tier III",
        "IV": "Tier IV",
        "V": "Tier V",
    }
    text_aliases = {
        "COMMON": "Common",
        "UNCOMMON": "Uncommon",
        "RARE": "Rare",
        "EPIC": "Epic",
        "LEGENDARY": "Legendary",
    }
    if normalized in numeral_aliases:
        return numeral_aliases[normalized]
    if normalized in text_aliases:
        return text_aliases[normalized]
    if normalized.startswith("TIER") and len(normalized) > 4:
        suffix = normalized[4:]
        return numeral_aliases.get(suffix, "")
    return ""
