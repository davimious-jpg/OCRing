from __future__ import annotations

from hashlib import sha1

from .buffer import EvidenceBuffer
from .models import CropEvidence, EvidenceKind, FieldKind, FrameRecord, Rect, RowZone


def build_crop_id(frame_id: str, row_id: str, field_kind: FieldKind, region: Rect) -> str:
    digest = sha1(
        f"{frame_id}|{row_id}|{field_kind.value}|{region.x1}|{region.y1}|{region.x2}|{region.y2}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def build_representative_evidence(
    frame: FrameRecord,
    row_zones: tuple[RowZone, ...],
) -> tuple[CropEvidence, ...]:
    evidence: list[CropEvidence] = []

    for zone_index, zone in enumerate(row_zones):
        for field_kind, rect in zone.fields.items():
            kind = EvidenceKind.REPRESENTATIVE
            if zone_index == 0 and field_kind is FieldKind.ITEM_NAME:
                kind = EvidenceKind.ANCHOR
            crop_id = build_crop_id(frame.frame_id, zone.row_id, field_kind, rect)
            evidence.append(
                CropEvidence(
                    crop_id=crop_id,
                    frame_id=frame.frame_id,
                    row_id=zone.row_id,
                    field_kind=field_kind,
                    region=rect,
                    evidence_kind=kind,
                    quality_score=round(rect.area / max(1, frame.inventory_region.area), 3),
                    metadata={
                        "profile_id": frame.profile_id,
                        "estimated_bytes": rect.area * 3,
                        "resolved_support": kind is EvidenceKind.REPRESENTATIVE,
                        "partial_frame": False,
                        "active_dependency": False,
                    },
                )
            )

    return tuple(evidence)
