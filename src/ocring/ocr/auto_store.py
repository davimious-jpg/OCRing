from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .text_quality import TextQualityState


class AutoStoreMode(str, Enum):
    STRICT_MANUAL_REVIEW = "Strict Manual Review"
    AUTO_STORE_VERIFIED_STABLE = "Auto Store Verified/Stable"


class AutoStoreDisposition(str, Enum):
    AUTO_STORE_ELIGIBLE = "AUTO_STORE_ELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HOLD_UNKNOWN = "HOLD/UNKNOWN"


@dataclass(frozen=True)
class AutoStoreDecision:
    disposition: AutoStoreDisposition
    eligible: bool
    reasons: tuple[str, ...]
    policy_rule: str


BLOCKING_REASON_TOKENS = (
    "CONTAMINATION",
    "UI_CATEGORY",
    "HEADER",
    "NAVIGATION",
    "STALE_DETAIL",
    "CONTRADICTION",
    "TEMPORAL_CONFLICT",
    "UNRESOLVED",
    "SYNTHESIZED",
    "FABRICATED",
    "SAME_FRAME_ONLY",
)


def evaluate_auto_store_eligibility(record: Any) -> AutoStoreDecision:
    fields = dict(getattr(record, "fields", {}) or {})
    field_details = dict(getattr(record, "field_details", {}) or {})
    support_summary = dict(getattr(record, "support_summary", {}) or {})
    reasons = [str(reason) for reason in (getattr(record, "reasons", ()) or ())]
    required_fields = tuple(str(field) for field in (getattr(record, "required_fields", ()) or ("item_name",)))
    missing_fields = tuple(str(field) for field in (getattr(record, "missing_fields", ()) or ()))

    item_name = str(fields.get("item_name") or "").strip()
    item_name_detail = _as_dict(field_details.get("item_name"))
    item_name_support = _as_dict(support_summary.get("item_name"))

    if not item_name or item_name.upper() == "UNKNOWN":
        return _decision(AutoStoreDisposition.HOLD_UNKNOWN, False, reasons, "ITEM_NAME_UNKNOWN")

    identity_status = str(item_name_detail.get("identity_status") or item_name_detail.get("status") or "")
    if identity_status != "OBSERVED_STABLE":
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, f"IDENTITY_NOT_STABLE:{identity_status or 'MISSING'}")

    if not bool(item_name_detail.get("direct_observation", False)):
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, "ITEM_NAME_NOT_DIRECT_OBSERVATION")

    independent_support = int(float(item_name_support.get("independent_support_count") or 0))
    if independent_support < 2:
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, "INDEPENDENT_SUPPORT_BELOW_AUTO_STORE_THRESHOLD")

    source_frame_ids = tuple(str(frame_id) for frame_id in (getattr(record, "source_frame_ids", ()) or ()) if str(frame_id))
    if len(set(source_frame_ids)) < 2:
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, "CHRONOLOGICAL_FRAME_SUPPORT_BELOW_AUTO_STORE_THRESHOLD")

    if not getattr(record, "source_row_ids", None):
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, "ROW_PROVENANCE_MISSING")

    missing_required_fields = tuple(field for field in missing_fields if field in required_fields)
    if missing_required_fields:
        return _decision(
            AutoStoreDisposition.NEEDS_REVIEW,
            False,
            reasons,
            *(f"REQUIRED_FIELD_MISSING:{field}" for field in missing_required_fields),
        )
    missing_required_reasons = tuple(
        reason
        for reason in reasons
        if reason.upper().endswith("_MISSING")
        and reason.upper() != "REFERENCE_DATA_MISSING"
        and _missing_reason_field(reason) in required_fields
    )
    if missing_required_reasons:
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, *missing_required_reasons)

    blocking = tuple(reason for reason in reasons if _is_blocking_reason(reason))
    if blocking:
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, *blocking)

    confidence = float(item_name_support.get("best_confidence") or item_name_detail.get("field_confidence") or 0.0)
    if confidence <= 0.0:
        return _decision(AutoStoreDisposition.NEEDS_REVIEW, False, reasons, "CONFIDENCE_MISSING")

    # Second gate: temporal stability (checked above, unchanged) proves
    # a reading repeats; it does not prove the repeated text is trustworthy. A
    # missing/blank text_quality_state means the record was never assessed
    # (e.g. an older fixture, or a non-item-name-driven path) and is treated as
    # passing, so this never blocks anything that could not already reach here.
    text_quality_state = str(item_name_detail.get("text_quality_state") or "")
    if text_quality_state == TextQualityState.LOW_OR_UNCERTAIN.value:
        text_quality_reasons = tuple(
            str(reason) for reason in (item_name_detail.get("text_quality_reasons") or ())
        )
        return _decision(
            AutoStoreDisposition.NEEDS_REVIEW,
            False,
            reasons,
            "TEXT_QUALITY_LOW_OR_UNCERTAIN",
            *text_quality_reasons,
        )

    return _decision(
        AutoStoreDisposition.AUTO_STORE_ELIGIBLE,
        True,
        reasons,
        "STRICT_STABLE_OBSERVED_IDENTITY",
    )


def auto_store_dedupe_key(record: Any) -> tuple[object, ...]:
    fields = dict(getattr(record, "fields", {}) or {})
    return (
        str(fields.get("item_name") or "").casefold(),
        str(fields.get("item_type") or "").casefold(),
        str(fields.get("item_rarity") or "").casefold(),
        str(fields.get("item_count") or "").casefold(),
        tuple(str(row_id) for row_id in (getattr(record, "source_row_ids", ()) or ())),
    )


def _decision(
    disposition: AutoStoreDisposition,
    eligible: bool,
    existing_reasons: list[str],
    *new_reasons: str,
) -> AutoStoreDecision:
    reasons = tuple(dict.fromkeys([*existing_reasons, *new_reasons]))
    return AutoStoreDecision(disposition, eligible, reasons, "STRICT_AUTO_STORE_POLICY")


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _is_blocking_reason(reason: str) -> bool:
    upper = reason.upper()
    return any(token in upper for token in BLOCKING_REASON_TOKENS)


def _missing_reason_field(reason: str) -> str:
    if not reason.upper().endswith("_MISSING"):
        return ""
    return reason.removesuffix("_MISSING").lower()
