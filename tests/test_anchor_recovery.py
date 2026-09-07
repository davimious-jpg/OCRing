from __future__ import annotations

from ocring.ocr.anchor_recovery import AnchorRecoveryEngine


def test_anchor_recovery_reestablishes_roi_from_anchor_shift() -> None:
    engine = AnchorRecoveryEngine()
    roi = {"x1": 100, "y1": 200, "x2": 300, "y2": 400}
    frame = {"anchors": ({"name": "inventory_label", "x": 70, "y": 90},)}
    anchors = ({"name": "inventory_label", "x": 50, "y": 60},)

    recovered = engine.recover_roi(roi, frame, anchors=anchors)

    assert recovered == {"x1": 120, "y1": 230, "x2": 320, "y2": 430}

