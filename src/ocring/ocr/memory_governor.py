from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryAction(str, Enum):
    KEEP = "KEEP"
    PIN = "PIN"
    COMPRESS = "COMPRESS"
    CROP = "CROP"
    FUSE = "FUSE"
    DROP = "DROP"
    DEFER = "DEFER"
    WARN_SLOW_DOWN = "WARN_SLOW_DOWN"


@dataclass(frozen=True)
class MemoryDecision:
    level: int
    level_name: str
    action: MemoryAction
    retained_budget_ratio: float
    reasons: tuple[str, ...]


class MemoryGovernor:
    LEVEL_NAMES = {
        0: "NORMAL",
        1: "TRIM",
        2: "COMPRESS",
        3: "PRIORITIZE",
        4: "DEGRADED",
        5: "WARN_USER",
    }

    def evaluate(
        self,
        *,
        ram_used: int,
        ram_limit: int,
        capture_fps: float,
        retained_fps: float,
        extraction_rate: float,
        raw_queue_depth: int,
        ocr_queue_depth: int,
        ai_queue_depth: int,
        motion_rate: float,
        frame_uniqueness: float,
        readability: float,
        continuity_anchors: int,
        unresolved_observations: int,
        cpu_load: float,
        gpu_load: float,
    ) -> MemoryDecision:
        ram_ratio = (ram_used / ram_limit) if ram_limit > 0 else 0.0
        total_queue_depth = raw_queue_depth + ocr_queue_depth + ai_queue_depth
        reasons: list[str] = []

        if continuity_anchors > 0:
            reasons.append("CONTINUITY_ANCHORS_PRESENT")
        if unresolved_observations > 0:
            reasons.append("UNRESOLVED_OBSERVATIONS_PRESENT")

        level = 0
        if ram_ratio >= 0.98 or total_queue_depth >= 48 or extraction_rate <= 0.15:
            level = 5
        elif ram_ratio >= 0.92 or total_queue_depth >= 32 or cpu_load >= 0.95 or gpu_load >= 0.95:
            level = 4
        elif ram_ratio >= 0.85 or total_queue_depth >= 20 or frame_uniqueness <= 0.30:
            level = 3
        elif ram_ratio >= 0.75 or retained_fps > max(extraction_rate * 2.0, 1.0):
            level = 2
        elif ram_ratio >= 0.65 or total_queue_depth >= 10 or frame_uniqueness <= 0.60:
            level = 1

        if level == 5:
            action = MemoryAction.WARN_SLOW_DOWN
            reasons.append("EXTRACTION_FALLING_BEHIND")
        elif level == 4:
            action = MemoryAction.DEFER if motion_rate > 0.5 and readability < 0.5 else MemoryAction.DROP
            reasons.append("CAPTURE_RETENTION_REDUCTION_REQUIRED")
        elif level == 3:
            action = MemoryAction.PIN if continuity_anchors > 0 or unresolved_observations > 0 else MemoryAction.CROP
            reasons.append("PRIORITIZE_ANCHORS_AND_NEW_ROWS")
        elif level == 2:
            action = MemoryAction.COMPRESS if readability >= 0.4 else MemoryAction.FUSE
            reasons.append("COMPACT_TO_BEST_REPRESENTATIVES")
        elif level == 1:
            action = MemoryAction.DROP if frame_uniqueness <= 0.60 else MemoryAction.KEEP
            reasons.append("DROP_DUPLICATE_FRAMES")
        else:
            action = MemoryAction.KEEP
            reasons.append("WITHIN_NORMAL_MEMORY_BOUNDS")

        if action is MemoryAction.KEEP and continuity_anchors > 0 and unresolved_observations > 0:
            action = MemoryAction.PIN
            reasons.append("PIN_ACTIVE_ANCHORS")

        retained_budget_ratio = max(0.05, round(1.0 - (level * 0.15), 3))
        if capture_fps > 0 and retained_fps > capture_fps:
            reasons.append("RETAINED_FPS_CLAMPED_TO_CAPTURE_FPS")

        return MemoryDecision(
            level=level,
            level_name=self.LEVEL_NAMES[level],
            action=action,
            retained_budget_ratio=retained_budget_ratio,
            reasons=tuple(dict.fromkeys(reasons)),
        )
