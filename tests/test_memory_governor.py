from __future__ import annotations

from ocring.ocr.buffer import EvidenceBuffer, FrameBufferState, ShortRawBuffer
from ocring.ocr.memory_governor import MemoryAction, MemoryGovernor
from ocring.ocr.models import CropEvidence, EvidenceKind, FieldKind, Rect


def _evidence(crop_id: str) -> CropEvidence:
    return CropEvidence(
        crop_id=crop_id,
        frame_id="f1",
        row_id=f"{crop_id}:row",
        field_kind=FieldKind.ITEM_NAME,
        region=Rect(0, 0, 10, 10),
        evidence_kind=EvidenceKind.REPRESENTATIVE,
        quality_score=0.5,
        metadata={"estimated_bytes": 1024, "resolved_support": True, "pixel_data": "placeholder"},
    )


def test_memory_governor_escalates_backpressure_levels() -> None:
    governor = MemoryGovernor()

    normal = governor.evaluate(
        ram_used=256 * 1024 * 1024,
        ram_limit=3 * 1024 * 1024 * 1024,
        capture_fps=30.0,
        retained_fps=20.0,
        extraction_rate=10.0,
        raw_queue_depth=1,
        ocr_queue_depth=1,
        ai_queue_depth=0,
        motion_rate=0.1,
        frame_uniqueness=0.9,
        readability=0.8,
        continuity_anchors=1,
        unresolved_observations=1,
        cpu_load=0.2,
        gpu_load=0.0,
    )
    critical = governor.evaluate(
        ram_used=int(2.99 * 1024 * 1024 * 1024),
        ram_limit=3 * 1024 * 1024 * 1024,
        capture_fps=60.0,
        retained_fps=55.0,
        extraction_rate=0.1,
        raw_queue_depth=20,
        ocr_queue_depth=20,
        ai_queue_depth=20,
        motion_rate=0.9,
        frame_uniqueness=0.1,
        readability=0.2,
        continuity_anchors=4,
        unresolved_observations=10,
        cpu_load=0.99,
        gpu_load=0.99,
    )

    assert normal.level == 0
    assert critical.level == 5
    assert critical.action is MemoryAction.WARN_SLOW_DOWN


def test_memory_governor_dynamic_budgeting_prefers_pin_or_compact() -> None:
    governor = MemoryGovernor()
    decision = governor.evaluate(
        ram_used=int(0.8 * 3 * 1024 * 1024 * 1024),
        ram_limit=3 * 1024 * 1024 * 1024,
        capture_fps=60.0,
        retained_fps=50.0,
        extraction_rate=12.0,
        raw_queue_depth=5,
        ocr_queue_depth=8,
        ai_queue_depth=3,
        motion_rate=0.2,
        frame_uniqueness=0.2,
        readability=0.7,
        continuity_anchors=3,
        unresolved_observations=6,
        cpu_load=0.5,
        gpu_load=0.3,
    )

    assert decision.level >= 2
    assert decision.retained_budget_ratio < 1.0
    assert decision.action in {MemoryAction.PIN, MemoryAction.COMPRESS, MemoryAction.CROP}


def test_frame_states_and_compact_provenance_work() -> None:
    raw = ShortRawBuffer(max_items=4)
    raw.retain("frame-1", {"frame_id": "frame-1"}, estimated_bytes=4096, state=FrameBufferState.RAW)
    raw.claim_by_ocr("frame-1")
    raw.pin("frame-1")
    assert raw.diagnostics()["ref_counts"]["frame-1"] == 2
    raw.release_ocr_claim("frame-1")
    raw.unpin("frame-1")
    assert raw.diagnostics()["states"]["frame-1"] == FrameBufferState.RELEASEABLE.value
    raw.transition("frame-1", FrameBufferState.DISCARDABLE)

    evidence_buffer = EvidenceBuffer(max_items=4)
    evidence_buffer.retain(_evidence("crop-1"))
    evidence_buffer.claim_by_ai("crop-1")
    evidence_buffer.pin("crop-1")
    assert evidence_buffer.diagnostics()["ref_counts"]["crop-1"] == 2
    evidence_buffer.release_ai_claim("crop-1")
    compacted = evidence_buffer.trim_to_compact_provenance()
    evidence_buffer.unpin("crop-1")

    assert raw.diagnostics()["states"]["frame-1"] == FrameBufferState.DISCARDABLE.value
    assert evidence_buffer.diagnostics()["states"]["crop-1"] in {
        FrameBufferState.RELEASEABLE.value,
        FrameBufferState.EXTRACTED.value,
    }
    assert compacted[0].metadata["compact_provenance"] is True
    assert "pixel_data" not in compacted[0].metadata
