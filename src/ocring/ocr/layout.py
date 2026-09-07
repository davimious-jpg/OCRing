from __future__ import annotations

from .models import FieldKind, FrameRecord, Rect, RowZone


def segment_inventory_rows(frame: FrameRecord, *, max_rows: int = 8) -> tuple[RowZone, ...]:
    region = frame.inventory_region
    row_height = max(1, region.height // max_rows)
    zones: list[RowZone] = []

    for index in range(max_rows):
        y1 = region.y1 + (index * row_height)
        y2 = region.y2 if index == max_rows - 1 else min(region.y2, y1 + row_height)
        row_bounds = Rect(region.x1, y1, region.x2, y2)
        if row_bounds.height < 8:
            continue

        name_end = region.x1 + int(row_bounds.width * 0.44)
        rarity_end = region.x1 + int(row_bounds.width * 0.60)
        type_end = region.x1 + int(row_bounds.width * 0.82)
        count_start = region.x1 + int(row_bounds.width * 0.90)

        zones.append(
            RowZone(
                row_id=f"{frame.frame_id}:row:{index + 1}",
                row_bounds=row_bounds,
                fields={
                    FieldKind.ITEM_NAME: Rect(region.x1, y1, name_end, y2),
                    FieldKind.ITEM_RARITY: Rect(name_end, y1, rarity_end, y2),
                    FieldKind.ITEM_TYPE: Rect(rarity_end, y1, type_end, y2),
                    FieldKind.ITEM_SYNERGY: Rect(type_end - int(row_bounds.width * 0.12), y1, count_start, y2),
                    FieldKind.ITEM_COUNT: Rect(count_start, y1, region.x2, y2),
                },
            )
        )

    return tuple(zones)

