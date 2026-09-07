from __future__ import annotations

from ocring.ocr.evidence import EvidenceBuffer
from ocring.ocr.models import CropEvidence, EvidenceKind, FieldKind, Rect


def test_evidence_buffer_trims_oldest_entry() -> None:
    buffer = EvidenceBuffer(max_items=2)

    buffer.retain(
        CropEvidence(
            crop_id="one",
            frame_id="f1",
            row_id="r1",
            field_kind=FieldKind.ITEM_NAME,
            region=Rect(0, 0, 10, 10),
            evidence_kind=EvidenceKind.REPRESENTATIVE,
            quality_score=0.5,
        )
    )
    buffer.retain(
        CropEvidence(
            crop_id="two",
            frame_id="f1",
            row_id="r2",
            field_kind=FieldKind.ITEM_NAME,
            region=Rect(0, 10, 10, 20),
            evidence_kind=EvidenceKind.REPRESENTATIVE,
            quality_score=0.5,
        )
    )
    buffer.retain(
        CropEvidence(
            crop_id="three",
            frame_id="f1",
            row_id="r3",
            field_kind=FieldKind.ITEM_NAME,
            region=Rect(0, 20, 10, 30),
            evidence_kind=EvidenceKind.REPRESENTATIVE,
            quality_score=0.5,
        )
    )

    retained = buffer.items()
    assert [item.crop_id for item in retained] == ["two", "three"]

