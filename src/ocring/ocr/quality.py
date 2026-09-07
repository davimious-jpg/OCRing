from __future__ import annotations

from .models import FrameQualityAction, FrameRecord, QualityMetrics


def assess_frame_quality(frame: FrameRecord) -> QualityMetrics:
    region = frame.inventory_region
    image = frame.image

    coverage = region.area / max(1, image.width * image.height)
    sharpness = min(1.0, 0.45 + coverage)
    contrast = min(1.0, 0.50 + (region.height / max(1, image.height)))
    motion_penalty = 0.0
    occlusion_penalty = 0.0
    partial_row_penalty = 0.0
    reasons: list[str] = []

    if coverage < 0.10:
        reasons.append("INVENTORY_REGION_TOO_SMALL")
        partial_row_penalty = 0.55
    if region.height < 120:
        reasons.append("INVENTORY_REGION_TOO_SHORT")
        sharpness = max(0.0, sharpness - 0.25)

    action = FrameQualityAction.KEEP
    if reasons:
        action = FrameQualityAction.DEFER
    if coverage < 0.05:
        action = FrameQualityAction.DROP

    return QualityMetrics(
        sharpness=round(sharpness, 3),
        motion_penalty=motion_penalty,
        contrast=round(contrast, 3),
        occlusion_penalty=occlusion_penalty,
        partial_row_penalty=partial_row_penalty,
        action=action,
        reasons=tuple(reasons),
    )

