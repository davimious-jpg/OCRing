from __future__ import annotations

from pathlib import Path

from ocring.ocr.auto_store import AutoStoreDisposition, AutoStoreMode, evaluate_auto_store_eligibility
from ocring.ocr.inventory import InventoryStore
from ocring.ocr.review import ReviewRecord, ReviewSession, ReviewStatus


def _stable_record(
    *,
    record_id: str = "record-1",
    item_name: str = "Shotgun Hip Spread V",
    reasons: list[str] | None = None,
    frames: list[str] | None = None,
    rows: list[str] | None = None,
    independent_support_count: int = 2,
    required_fields: list[str] | None = None,
    missing_fields: list[str] | None = None,
    text_quality_state: str | None = None,
    text_quality_reasons: list[str] | None = None,
) -> ReviewRecord:
    frames = frames or ["frame-1", "frame-2"]
    rows = rows or ["frame-1:row:10", "frame-2:row:10"]
    return ReviewRecord(
        record_id=record_id,
        row_slot=10,
        fields={
            "item_name": item_name,
            "item_rarity": "Tier IV",
            "item_count": "1",
            "item_type": "Shotgun",
        },
        support_summary={
            "item_name": {
                "support_state": "supported",
                "support_count": len(frames),
                "independent_support_count": independent_support_count,
                "best_confidence": 0.89,
                "source_frame_ids": frames,
                "source_row_ids": rows,
                "source_crop_ids": ["crop-1", "crop-2"],
            }
        },
        source_frame_ids=frames,
        source_row_ids=rows,
        overlap_provenance={},
        reasons=reasons or ["REFERENCE_DATA_MISSING"],
        field_details={
            "item_name": {
                "source_text": item_name,
                "raw_observation": item_name,
                "status": "OBSERVED_STABLE",
                "identity_status": "OBSERVED_STABLE",
                "reference_status": "REFERENCE_DATA_MISSING",
                "field_confidence": 0.89,
                "direct_observation": True,
                "text_quality_state": text_quality_state or "AUTO_STORE_TRUSTWORTHY",
                "text_quality_reasons": text_quality_reasons or [],
            }
        },
        record_class="WeaponMod",
        required_fields=required_fields or ["item_name"],
        missing_fields=missing_fields or [],
    )


def test_stable_observed_record_is_auto_store_eligible_with_missing_reference_data() -> None:
    decision = evaluate_auto_store_eligibility(_stable_record())

    assert decision.disposition is AutoStoreDisposition.AUTO_STORE_ELIGIBLE
    assert decision.eligible is True
    assert "REFERENCE_DATA_MISSING" in decision.reasons


def test_unstable_identity_goes_to_review() -> None:
    record = _stable_record()
    record.field_details["item_name"]["identity_status"] = "OBSERVED_UNSTABLE"

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert decision.eligible is False


def test_unknown_identity_never_auto_stores() -> None:
    record = _stable_record(item_name="UNKNOWN")

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.HOLD_UNKNOWN
    assert decision.eligible is False


def test_ui_contamination_never_auto_stores() -> None:
    record = _stable_record(reasons=["REFERENCE_DATA_MISSING", "UI_CATEGORY_CONTAMINATION"])

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert decision.eligible is False


def test_missing_required_field_reason_routes_to_review() -> None:
    record = _stable_record(
        reasons=["REFERENCE_DATA_MISSING", "ITEM_TYPE_MISSING"],
        required_fields=["item_name", "item_type"],
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert decision.eligible is False
    assert "ITEM_TYPE_MISSING" in decision.reasons


def test_optional_missing_field_reason_does_not_block_stable_observed_record() -> None:
    record = _stable_record(
        reasons=["REFERENCE_DATA_MISSING", "ITEM_TYPE_MISSING"],
        required_fields=["item_name"],
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.AUTO_STORE_ELIGIBLE
    assert decision.eligible is True


def test_missing_required_field_metadata_routes_to_review() -> None:
    record = _stable_record(
        required_fields=["item_name", "item_type"],
        missing_fields=["item_type"],
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert "REQUIRED_FIELD_MISSING:item_type" in decision.reasons


def test_stable_but_text_quality_low_blocks_auto_store() -> None:
    # Temporally stable (support_state=supported, independent_support_count=2,
    # identity_status=OBSERVED_STABLE) but flagged by the text-quality gate -
    # this is the "temporally stable is not the same as textually trustworthy" case.
    record = _stable_record(
        item_name="Aaie Baid Maay",
        text_quality_state="STABLE_BUT_REVIEW_REQUIRED",
        text_quality_reasons=["MEAN_CONFIDENCE_BELOW_FLOOR", "PREPROCESS_AGREEMENT_BELOW_FLOOR"],
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert decision.eligible is False
    assert "TEXT_QUALITY_LOW_OR_UNCERTAIN" in decision.reasons
    assert "MEAN_CONFIDENCE_BELOW_FLOOR" in decision.reasons
    assert "PREPROCESS_AGREEMENT_BELOW_FLOOR" in decision.reasons


def test_clean_high_quality_text_remains_auto_store_eligible() -> None:
    record = _stable_record(
        item_name="Tight Guidance System IV",
        text_quality_state="AUTO_STORE_TRUSTWORTHY",
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.AUTO_STORE_ELIGIBLE
    assert decision.eligible is True


def test_missing_text_quality_assessment_does_not_block_legacy_records() -> None:
    # A record built before this gate existed (no text_quality_state key at
    # all) must not be newly blocked - the gate only acts when it actually
    # ran an assessment.
    record = _stable_record()
    del record.field_details["item_name"]["text_quality_state"]

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.AUTO_STORE_ELIGIBLE
    assert decision.eligible is True


def test_text_quality_gate_does_not_alter_observed_text_or_provenance() -> None:
    # Review must see the original observed text and provenance unchanged -
    # the gate blocks auto-store, it never corrects or hides the reading.
    record = _stable_record(
        item_name="Aaie Baid Maay",
        text_quality_state="STABLE_BUT_REVIEW_REQUIRED",
        text_quality_reasons=["MEAN_CONFIDENCE_BELOW_FLOOR"],
    )

    evaluate_auto_store_eligibility(record)

    assert record.fields["item_name"] == "Aaie Baid Maay"
    assert record.field_details["item_name"]["source_text"] == "Aaie Baid Maay"
    assert record.field_details["item_name"]["raw_observation"] == "Aaie Baid Maay"
    assert record.field_details["item_name"]["identity_status"] == "OBSERVED_STABLE"
    assert record.source_frame_ids == ["frame-1", "frame-2"]
    assert record.support_summary["item_name"]["independent_support_count"] == 2


def test_same_frame_variants_do_not_qualify() -> None:
    record = _stable_record(
        frames=["frame-1", "frame-1"],
        rows=["frame-1:row:10", "frame-1:row:10"],
        independent_support_count=1,
    )

    decision = evaluate_auto_store_eligibility(record)

    assert decision.disposition is AutoStoreDisposition.NEEDS_REVIEW
    assert "INDEPENDENT_SUPPORT_BELOW_AUTO_STORE_THRESHOLD" in decision.reasons


def test_review_session_auto_store_mode_preserves_exception_queue() -> None:
    stable = _stable_record(record_id="record-stable")
    unknown = _stable_record(record_id="record-unknown", item_name="UNKNOWN")
    session = ReviewSession("session-1", [stable, unknown])

    summary = session.apply_auto_store_policy(AutoStoreMode.AUTO_STORE_VERIFIED_STABLE.value)

    assert summary["automatically_stored"] == 1
    assert summary["hold_unknown"] == 1
    assert stable.review_status == ReviewStatus.AUTO_SAVED
    assert unknown.review_status == ReviewStatus.PENDING
    assert session.get_exception_records() == [unknown]


def test_strict_manual_review_mode_does_not_auto_store() -> None:
    record = _stable_record()
    session = ReviewSession("session-1", [record])

    summary = session.apply_auto_store_policy(AutoStoreMode.STRICT_MANUAL_REVIEW.value)

    assert summary["automatically_stored"] == 0
    assert summary["needs_manual_review"] == 1
    assert record.review_status == ReviewStatus.PENDING


def test_provenance_survives_automatic_commit(tmp_path: Path) -> None:
    record = _stable_record()
    session = ReviewSession("session-1", [record])
    session.apply_auto_store_policy(AutoStoreMode.AUTO_STORE_VERIFIED_STABLE.value)

    count = InventoryStore(tmp_path / "inventory.db").commit_reviewed_records(session)
    stored = InventoryStore(tmp_path / "inventory.db").get_all_verified_records()

    assert count == 1
    assert stored[0].review_status == ReviewStatus.AUTO_SAVED
    assert stored[0].corrections["_auto_store"]["eligible"] is True
    assert stored[0].corrections["_provenance"]["source_frame_ids"] == ["frame-1", "frame-2"]


def test_duplicate_stable_observations_do_not_create_duplicate_auto_saved_rows(tmp_path: Path) -> None:
    first = _stable_record(record_id="record-1")
    duplicate = _stable_record(record_id="record-2")
    session = ReviewSession("session-1", [first, duplicate])

    summary = session.apply_auto_store_policy(AutoStoreMode.AUTO_STORE_VERIFIED_STABLE.value)
    count = InventoryStore(tmp_path / "inventory.db").commit_reviewed_records(session)

    assert summary["automatically_stored"] == 1
    assert summary["duplicate_suppressions"] == 1
    assert count == 1
