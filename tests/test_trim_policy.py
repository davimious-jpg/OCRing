from __future__ import annotations

from ocring.ocr.buffer import EvidenceBuffer
from ocring.ocr.models import CropEvidence, EvidenceKind, FieldKind, Rect
from ocring.ocr.trim_policy import TrimPolicy


def _evidence(
    crop_id: str,
    *,
    kind: EvidenceKind = EvidenceKind.REPRESENTATIVE,
    quality_score: float = 0.5,
    metadata: dict | None = None,
) -> CropEvidence:
    return CropEvidence(
        crop_id=crop_id,
        frame_id="f1",
        row_id=f"{crop_id}:row",
        field_kind=FieldKind.ITEM_NAME,
        region=Rect(0, 0, 10, 10),
        evidence_kind=kind,
        quality_score=quality_score,
        metadata=metadata or {},
    )


def test_should_trim_returns_true_when_ram_exceeds_threshold() -> None:
    policy = TrimPolicy(
        ram_pressure=0.81,
        cpu_pressure=0.10,
        queue_depth=0,
        buffer_occupancy=0.10,
    )

    assert policy.should_trim() is True


def test_duplicate_frames_trim_before_unique_anchors() -> None:
    policy = TrimPolicy(
        ram_pressure=0.90,
        cpu_pressure=0.10,
        queue_depth=0,
        buffer_occupancy=0.90,
    )
    duplicate = _evidence("dup", metadata={"duplicate_frame": True})
    anchor = _evidence("anchor", kind=EvidenceKind.ANCHOR)

    targets = policy.get_trim_targets((anchor, duplicate), policy.pressure_level())

    assert targets[0].crop_id == "dup"


def test_unresolved_evidence_is_preserved_under_high_pressure() -> None:
    policy = TrimPolicy(
        ram_pressure=0.98,
        cpu_pressure=0.10,
        queue_depth=100,
        buffer_occupancy=0.99,
    )
    unresolved = _evidence("unresolved", metadata={"unresolved_record_only": True})
    duplicate = _evidence("dup", metadata={"duplicate_frame": True})

    targets = policy.get_trim_targets((unresolved, duplicate), policy.pressure_level())

    assert all(item.crop_id != "unresolved" for item in targets)


def test_trim_evidence_does_not_crash_when_buffer_is_empty() -> None:
    buffer = EvidenceBuffer()

    trimmed = buffer.trim_evidence({"ram_pressure": 0.99, "cpu_pressure": 0.99, "queue_depth": 100, "buffer_occupancy": 1.0})

    assert trimmed == ()


def test_trim_count_increments_correctly() -> None:
    buffer = EvidenceBuffer(max_items=10)
    buffer.retain(_evidence("dup-1", metadata={"duplicate_frame": True, "estimated_bytes": 300}))
    buffer.retain(_evidence("dup-2", metadata={"duplicate_frame": True, "estimated_bytes": 300}))
    buffer.retain(_evidence("anchor", kind=EvidenceKind.ANCHOR, metadata={"estimated_bytes": 300}))

    trimmed = buffer.trim_evidence({"ram_pressure": 0.99, "cpu_pressure": 0.10, "queue_depth": 0, "buffer_occupancy": 0.95})

    assert trimmed
    assert buffer.trim_count == 1
    assert buffer.total_trimmed_bytes > 0
    assert buffer.last_trim_reason.startswith("TRIM_EVENT:")
