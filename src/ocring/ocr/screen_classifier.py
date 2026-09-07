from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .models import FrameRecord


class ScreenClass(str, Enum):
    INVENTORY = "inventory"
    VENDOR = "vendor"
    MOD_DETAIL = "mod_detail"
    LOADOUT = "loadout"
    STASH = "stash"
    CRAFTING = "crafting"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScreenClassification:
    screen_class: ScreenClass
    reason: str
    evidence: dict[str, float | int | bool] = field(default_factory=dict)

    @property
    def hold_reason(self) -> str:
        if self.screen_class is ScreenClass.UNKNOWN:
            return "UNKNOWN_SCREEN"
        if self.screen_class is ScreenClass.INVENTORY:
            return ""
        return f"{self.screen_class.value.upper()}_REFERENCE_ONLY"


class ScreenClassifier:
    _TOKEN_MAP = {
        "inventory": ScreenClass.INVENTORY,
        "vendor": ScreenClass.VENDOR,
        "mod": ScreenClass.MOD_DETAIL,
        "loadout": ScreenClass.LOADOUT,
        "stash": ScreenClass.STASH,
        "crafting": ScreenClass.CRAFTING,
        "comparison": ScreenClass.COMPARISON,
        "compare": ScreenClass.COMPARISON,
    }

    def classify(self, frame: FrameRecord) -> ScreenClassification:
        token_match = self._class_from_tokens(frame)
        if token_match is not None and token_match is not ScreenClass.INVENTORY:
            return ScreenClassification(token_match, "TOKEN_HEURISTIC")

        color_match = self._class_from_color(frame)
        if color_match is not None:
            return ScreenClassification(color_match, "COLOR_REGION_HEURISTIC")

        evidence = self._visible_evidence(frame)
        if not evidence:
            return ScreenClassification(ScreenClass.UNKNOWN, "NO_VISIBLE_SCREEN_EVIDENCE")

        # Gameplay signatures veto a projected inventory ROI. A profile ROI exists
        # on every frame, including combat, so geometry alone is never sufficient.
        if bool(evidence["strong_combat_negative"]):
            return ScreenClassification(ScreenClass.UNKNOWN, "COMBAT_EVIDENCE_VETO", evidence)
        if not bool(evidence["row_list_structure_evidence"]):
            return ScreenClassification(ScreenClass.UNKNOWN, "NO_CREDIBLE_ROW_LIST_STRUCTURE", evidence)
        if int(evidence["inventory_positive_count"]) >= 2:
            return ScreenClassification(ScreenClass.INVENTORY, "COMBINED_INVENTORY_EVIDENCE", evidence)
        return ScreenClassification(ScreenClass.UNKNOWN, "INSUFFICIENT_INVENTORY_EVIDENCE", evidence)

    def _class_from_tokens(self, frame: FrameRecord) -> ScreenClass | None:
        token_source = f"{frame.image.path} {frame.detector_name}".lower()
        for token, screen_class in self._TOKEN_MAP.items():
            if token in token_source:
                return screen_class
        return None

    def _class_from_color(self, frame: FrameRecord) -> ScreenClass | None:
        image_path = Path(frame.image.path)
        if not image_path.exists():
            return None
        try:
            from PIL import Image
        except ImportError:
            return None

        with Image.open(image_path) as image:
            rgb = image.convert("RGB").resize((8, 8))
            pixels = list(rgb.getdata())
        if not pixels:
            return None
        mean_r = sum(pixel[0] for pixel in pixels) / len(pixels)
        mean_g = sum(pixel[1] for pixel in pixels) / len(pixels)
        mean_b = sum(pixel[2] for pixel in pixels) / len(pixels)

        if mean_r > 170 and mean_g > 90 and mean_b < 120:
            return ScreenClass.CRAFTING
        if mean_b > 150 and mean_g > 120 and mean_r < 120:
            return ScreenClass.COMPARISON
        if mean_g > 140 and mean_r < 130:
            return ScreenClass.STASH
        return None

    def _visible_evidence(self, frame: FrameRecord) -> dict[str, float | int | bool]:
        image_path = Path(frame.image.path)
        if not image_path.exists():
            return {}
        try:
            from PIL import Image
        except ImportError:
            return {}

        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            source_width, source_height = rgb.size
            sample = rgb.resize((256, 144))
        pixels = sample.load()
        width, height = sample.size

        def scaled_rect(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
            return (
                max(0, min(width, round(x1 * width))),
                max(0, min(height, round(y1 * height))),
                max(0, min(width, round(x2 * width))),
                max(0, min(height, round(y2 * height))),
            )

        def ratios(bounds: tuple[int, int, int, int]) -> tuple[float, float, float]:
            x1, y1, x2, y2 = bounds
            total = max(1, (x2 - x1) * (y2 - y1))
            red = cyan = dark = 0
            for y in range(y1, y2):
                for x in range(x1, x2):
                    value_r, value_g, value_b = pixels[x, y]
                    red += value_r > 150 and value_g < 100 and value_b < 100
                    cyan += value_g > value_r * 1.2 and value_b > value_r * 1.1 and value_g > 80
                    dark += value_r < 50 and value_g < 50 and value_b < 50
            return red / total, cyan / total, dark / total

        coverage = frame.inventory_region.area / max(1, frame.image.width * frame.image.height)
        inventory_x1 = max(0, min(width - 1, round(frame.inventory_region.x1 / max(1, source_width) * width)))
        inventory_x2 = max(inventory_x1 + 1, min(width, round(frame.inventory_region.x2 / max(1, source_width) * width)))
        inventory_y1 = max(1, min(height - 1, round(frame.inventory_region.y1 / max(1, source_height) * height)))
        inventory_y2 = max(inventory_y1 + 1, min(height, round(frame.inventory_region.y2 / max(1, source_height) * height)))

        def row_luma(y: int) -> float:
            return sum(sum(pixels[x, y]) / 3 for x in range(inventory_x1, inventory_x2)) / max(1, inventory_x2 - inventory_x1)

        expected_rows = 11
        row_edges: list[float] = []
        for row_index in range(expected_rows + 1):
            expected_y = round(inventory_y1 + (inventory_y2 - inventory_y1) * row_index / expected_rows)
            nearby = range(max(inventory_y1 + 1, expected_y - 1), min(inventory_y2 - 1, expected_y + 1) + 1)
            row_edges.append(max((abs(row_luma(y) - row_luma(y - 1)) for y in nearby), default=0.0))

        top_center_red, _, _ = ratios(scaled_rect(0.30, 0.02, 0.70, 0.24))
        _, global_cyan, _ = ratios((0, 0, width, height))
        _, detail_cyan, detail_dark = ratios(scaled_rect(0.73, 0.10, 0.95, 0.80))
        row_edge_count = sum(edge >= 5.0 for edge in row_edges)
        row_edge_average = sum(row_edges) / len(row_edges)
        row_alignment = row_edge_count >= 8 and row_edge_average >= 18.0
        row_list_structure = row_edge_count >= 6 and row_edge_average >= 15.0
        panel_evidence = global_cyan >= 0.10 and (detail_dark >= 0.25 or detail_cyan >= 0.12)
        geometry_evidence = coverage >= 0.12
        strong_combat_negative = top_center_red >= 0.03 and not row_alignment
        positive_count = sum((geometry_evidence, row_list_structure, panel_evidence))
        return {
            "inventory_roi_coverage": round(coverage, 3),
            "row_edge_count": row_edge_count,
            "row_edge_average": round(row_edge_average, 3),
            "global_cyan_ratio": round(global_cyan, 4),
            "detail_dark_ratio": round(detail_dark, 4),
            "detail_cyan_ratio": round(detail_cyan, 4),
            "top_center_red_ratio": round(top_center_red, 4),
            "geometry_evidence": geometry_evidence,
            "row_alignment_evidence": row_alignment,
            "row_list_structure_evidence": row_list_structure,
            "panel_evidence": panel_evidence,
            "inventory_positive_count": positive_count,
            "strong_combat_negative": strong_combat_negative,
        }
