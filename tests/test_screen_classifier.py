from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ocring.ocr.models import FrameImage, FrameRecord, Rect
from ocring.ocr.screen_classifier import ScreenClass, ScreenClassifier

# These three tests regress against real captured gameplay screenshots kept
# only in a local, non-published evidence folder (too large/private for the
# public repository). They skip cleanly instead of failing when that local
# evidence isn't present.
EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "output" / "evidence"


def _require_evidence(filename: str) -> Path:
    path = EVIDENCE_DIR / filename
    if not path.exists():
        pytest.skip(f"local evidence fixture not present: {filename}")
    return path


def _make_frame(image_path: Path, *, detector_name: str = "default") -> FrameRecord:
    return FrameRecord(
        frame_id="frame-1",
        session_id="session-1",
        profile_id="defiance",
        timestamp_utc="2026-08-16T00:00:00+00:00",
        image=FrameImage(path=str(image_path), width=1920, height=1080),
        inventory_region=Rect(100, 100, 1500, 900),
        detector_name=detector_name,
    )


def test_screen_classifier_uses_filename_token_for_non_inventory_screen(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory_screen.png"
    vendor_path = tmp_path / "vendor_screen.png"
    Image.new("RGB", (64, 64), (50, 50, 50)).save(inventory_path)
    Image.new("RGB", (64, 64), (50, 50, 50)).save(vendor_path)

    classifier = ScreenClassifier()

    # The inventory filename is not production evidence. It must not bypass the
    # visible-pixel decision used for real Defiance captures.
    assert classifier.classify(_make_frame(inventory_path)).screen_class is ScreenClass.UNKNOWN
    assert classifier.classify(_make_frame(vendor_path)).screen_class is ScreenClass.VENDOR


def test_screen_classifier_uses_color_region_fallback(tmp_path: Path) -> None:
    stash_path = tmp_path / "plain.png"
    Image.new("RGB", (64, 64), (40, 180, 60)).save(stash_path)

    result = ScreenClassifier().classify(_make_frame(stash_path, detector_name="plain"))

    assert result.screen_class is ScreenClass.STASH
    assert result.reason == "COLOR_REGION_HEURISTIC"


def test_screen_classifier_returns_unknown_when_no_heuristic_matches(tmp_path: Path) -> None:
    unknown_path = tmp_path / "mystery.png"
    Image.new("RGB", (64, 64), (40, 40, 40)).save(unknown_path)
    frame = FrameRecord(
        frame_id="frame-1",
        session_id="session-1",
        profile_id="defiance",
        timestamp_utc="2026-08-16T00:00:00+00:00",
        image=FrameImage(path=str(unknown_path), width=1920, height=1080),
        inventory_region=Rect(0, 0, 200, 100),
        detector_name="plain",
    )

    result = ScreenClassifier().classify(frame)

    assert result.screen_class is ScreenClass.UNKNOWN
    assert result.hold_reason == "UNKNOWN_SCREEN"


def _real_captured_frame(image_path: Path, *, frame_id: str) -> FrameRecord:
    with Image.open(image_path) as image:
        width, height = image.size
    return FrameRecord(
        frame_id=frame_id,
        session_id="real-capture-session",
        profile_id="defiance",
        timestamp_utc="2026-09-02T16:00:00+00:00",
        image=FrameImage(path=str(image_path), width=width, height=height),
        inventory_region=Rect(51, 63, 982, 654),
        detector_name="profile_roi_projection",
    )


def test_screen_classifier_uses_retained_real_inventory_and_combat_evidence() -> None:
    inventory_path = _require_evidence("sample-inventory-screen.png")
    combat_path = _require_evidence("sample-combat-false-positive.png")

    classifier = ScreenClassifier()
    inventory = classifier.classify(_real_captured_frame(inventory_path, frame_id="inventory"))
    combat = classifier.classify(_real_captured_frame(combat_path, frame_id="combat"))

    assert inventory.screen_class is ScreenClass.INVENTORY
    assert inventory.reason == "COMBINED_INVENTORY_EVIDENCE"
    assert inventory.evidence["inventory_positive_count"] >= 2
    assert combat.screen_class is ScreenClass.UNKNOWN
    assert combat.reason == "COMBAT_EVIDENCE_VETO"
    assert combat.evidence["strong_combat_negative"] is True


def test_screen_classifier_returns_unknown_for_ambiguous_geometry_only_frame(tmp_path: Path) -> None:
    ambiguous_path = tmp_path / "ambiguous.png"
    Image.new("RGB", (1366, 768), (40, 40, 40)).save(ambiguous_path)

    result = ScreenClassifier().classify(_real_captured_frame(ambiguous_path, frame_id="ambiguous"))

    assert result.screen_class is ScreenClass.UNKNOWN
    assert result.reason == "NO_CREDIBLE_ROW_LIST_STRUCTURE"


def test_screen_classifier_inventory_combat_inventory_transition_has_no_combat_rows() -> None:
    from ocring.ocr.pipeline import _capture_frame_state

    inventory_path = _require_evidence("sample-inventory-screen.png")
    combat_path = _require_evidence("sample-combat-false-positive.png")
    classifier = ScreenClassifier()
    sequence = [inventory_path, combat_path, inventory_path]
    classes = [classifier.classify(_real_captured_frame(path, frame_id=f"frame-{index}")).screen_class for index, path in enumerate(sequence, start=1)]
    combat_state = _capture_frame_state(
        combat_path,
        profile_id="defiance",
        frame_id="combat",
        session_id="real-capture-session",
        timestamp_utc="2026-09-02T16:00:00+00:00",
        image_source="live_capture",
    )

    assert classes == [ScreenClass.INVENTORY, ScreenClass.UNKNOWN, ScreenClass.INVENTORY]
    assert combat_state.screen_classification.screen_class is ScreenClass.UNKNOWN
    assert combat_state.row_zones == ()


def test_screen_classifier_rejects_real_loadout_category_ui_regression() -> None:
    from ocring.ocr.pipeline import IMAGE_SOURCE_LIVE_CAPTURE, _build_frame_report, _capture_frame_state

    regression_path = _require_evidence("sample-loadout-category-contamination.png")

    state = _capture_frame_state(
        regression_path,
        profile_id="defiance",
        frame_id="session-c4fcc53d-frame-000013",
        session_id="session-c4fcc53d",
        timestamp_utc="2026-09-02T22:44:35.669900+00:00",
        image_source=IMAGE_SOURCE_LIVE_CAPTURE,
    )
    report = _build_frame_report(
        regression_path,
        profile_id="defiance",
        frame_id="session-c4fcc53d-frame-000013",
        session_id="session-c4fcc53d",
        timestamp_utc="2026-09-02T22:44:35.669900+00:00",
        capture_state=state,
        image_source=IMAGE_SOURCE_LIVE_CAPTURE,
    )

    assert state.screen_classification.screen_class is not ScreenClass.INVENTORY
    assert state.row_zones == ()
    assert report.screen_class != ScreenClass.INVENTORY.value
    assert report.row_zones == ()
    assert report.prepared_crops == ()
    assert report.ocr_attempts == ()
    assert report.ranked_candidates == ()
