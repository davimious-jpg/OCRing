from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from PIL import Image

from .models import FieldKind, PreparedFieldCrop, Rect, RowZone
from .profile import create_default_template, load_profile
from .preprocess import preprocess_field_crop


def prepare_row_field_crops(
    image_path: Path,
    row_zones: tuple[RowZone, ...],
    *,
    profile_id: str = "defiance",
) -> tuple[PreparedFieldCrop, ...]:
    crops: list[PreparedFieldCrop] = []
    screen_config = _load_inventory_screen_config(profile_id)
    profile_regions = _normalize_profile_regions(screen_config.get("field_regions", {}))

    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        for zone in row_zones:
            field_regions = _resolve_zone_fields(zone, profile_regions)
            for field_kind, rect in field_regions.items():
                variants = preprocess_field_crop(rgb, rect)
                for variant in variants:
                    crop_id = _build_crop_id(zone.row_id, field_kind.value, variant.variant.value, rect)
                    crops.append(
                        PreparedFieldCrop(
                            crop_id=crop_id,
                            row_id=zone.row_id,
                            field_kind=field_kind,
                            variant=variant.variant,
                            source_region=rect,
                            width=variant.width,
                            height=variant.height,
                            stats=variant.stats,
                        )
                    )

    return tuple(crops)


def prepare_selected_detail_field_crops(
    image_path: Path,
    inventory_region: Rect,
    *,
    selected_row_id: str,
    profile_id: str = "defiance",
    layout_name: str | None = None,
) -> tuple[PreparedFieldCrop, ...]:
    crops: list[PreparedFieldCrop] = []
    selected_layout = _resolve_selected_detail_layout(profile_id, layout_name=layout_name)
    if not selected_layout:
        return ()
    detail_regions = dict(selected_layout.get("regions", {}))

    field_map = {
        "detail_title_region": FieldKind.ITEM_NAME,
        "detail_type_region": FieldKind.ITEM_TYPE,
        "detail_synergy_region": FieldKind.ITEM_SYNERGY,
        "detail_rarity_region": FieldKind.ITEM_RARITY,
    }

    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        region_space = str(selected_layout.get("region_space") or "inventory").strip().lower()
        if region_space == "frame":
            base_region = Rect(0, 0, rgb.width, rgb.height)
        else:
            base_region = inventory_region
        base_width = max(1, base_region.width)
        base_height = max(1, base_region.height)
        for region_name, field_kind in field_map.items():
            rect = detail_regions.get(region_name)
            if not rect:
                continue
            source_region = Rect(
                x1=base_region.x1 + int(base_width * rect["x1"]),
                y1=base_region.y1 + int(base_height * rect["y1"]),
                x2=base_region.x1 + int(base_width * rect["x2"]),
                y2=base_region.y1 + int(base_height * rect["y2"]),
            )
            variants = preprocess_field_crop(rgb, source_region)
            for variant in variants:
                crops.append(
                    PreparedFieldCrop(
                        crop_id=_build_detail_crop_id(
                            selected_row_id,
                            detail_label=region_name,
                            field_kind=field_kind.value,
                            variant=variant.variant.value,
                            rect=source_region,
                        ),
                        row_id=selected_row_id,
                        field_kind=field_kind,
                        variant=variant.variant,
                        source_region=source_region,
                        width=variant.width,
                        height=variant.height,
                        stats=variant.stats,
                    )
                )

    return tuple(crops)


def load_selected_detail_panel_layouts(profile_id: str = "defiance") -> tuple[dict[str, object], ...]:
    screen_config = _load_inventory_screen_config(profile_id)
    layouts = _normalize_selected_detail_layouts(screen_config)
    if layouts:
        return layouts
    detail_regions = _normalize_profile_regions(screen_config.get("selected_detail_panel_regions", {}))
    if not detail_regions:
        return ()
    return (
        {
            "name": "default",
            "region_space": str(screen_config.get("selected_detail_panel_region_space") or "inventory").strip().lower(),
            "regions": detail_regions,
        },
    )


def _build_crop_id(row_id: str, field_kind: str, variant: str, rect) -> str:
    digest = sha1(
        f"{row_id}|{field_kind}|{variant}|{rect.x1}|{rect.y1}|{rect.x2}|{rect.y2}".encode("utf-8")
    ).hexdigest()
    return digest[:20]


def _build_detail_crop_id(row_id: str, *, detail_label: str, field_kind: str, variant: str, rect: Rect) -> str:
    digest = sha1(
        f"detail|{row_id}|{detail_label}|{field_kind}|{variant}|{rect.x1}|{rect.y1}|{rect.x2}|{rect.y2}".encode("utf-8")
    ).hexdigest()
    return f"detail-{detail_label}-{digest[:16]}"


def _load_inventory_screen_config(profile_id: str) -> dict[str, object]:
    try:
        profile = load_profile(profile_id)
    except OSError:
        profile = create_default_template()
    for screen in profile.screens:
        if str(screen.get("screen_class", "")).strip().lower() == "inventory":
            return dict(screen)
    return {}


def _normalize_profile_regions(raw_regions: object) -> dict[str, dict[str, float]]:
    if not isinstance(raw_regions, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for key, rect in raw_regions.items():
        if isinstance(rect, dict):
            normalized[str(key)] = {
                axis: float(rect.get(axis, 0.0))
                for axis in ("x1", "y1", "x2", "y2")
            }
    return normalized


def _normalize_selected_detail_layouts(screen_config: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw_layouts = screen_config.get("selected_detail_panel_layouts", {})
    if not isinstance(raw_layouts, dict):
        return ()
    layouts: list[dict[str, object]] = []
    for name, payload in raw_layouts.items():
        if not isinstance(payload, dict):
            continue
        regions = _normalize_profile_regions(payload.get("regions", {}))
        if not regions:
            continue
        layouts.append(
            {
                "name": str(name),
                "region_space": str(payload.get("region_space") or screen_config.get("selected_detail_panel_region_space") or "inventory").strip().lower(),
                "regions": regions,
            }
        )
    return tuple(layouts)


def _resolve_selected_detail_layout(profile_id: str, *, layout_name: str | None) -> dict[str, object]:
    layouts = load_selected_detail_panel_layouts(profile_id)
    if not layouts:
        return {}
    if layout_name is None:
        return dict(layouts[0])
    normalized_name = str(layout_name).strip().lower()
    for layout in layouts:
        if str(layout.get("name", "")).strip().lower() == normalized_name:
            return dict(layout)
    return {}


def _resolve_zone_fields(
    zone: RowZone,
    profile_regions: dict[str, dict[str, float]],
):
    if not profile_regions:
        return zone.fields
    from .models import FieldKind, Rect

    field_map = {
        "item_name_region": FieldKind.ITEM_NAME,
        "rarity_color_region": FieldKind.ITEM_RARITY,
        "synergy_region": FieldKind.ITEM_SYNERGY,
        "quantity_region": FieldKind.ITEM_COUNT,
    }
    resolved = {}
    row_bounds = zone.row_bounds
    row_width = max(1, row_bounds.width)
    row_height = max(1, row_bounds.height)
    for region_name, field_kind in field_map.items():
        rect = profile_regions.get(region_name)
        if not rect:
            continue
        resolved[field_kind] = Rect(
            x1=row_bounds.x1 + int(row_width * rect["x1"]),
            y1=row_bounds.y1 + int(row_height * rect["y1"]),
            x2=row_bounds.x1 + int(row_width * rect["x2"]),
            y2=row_bounds.y1 + int(row_height * rect["y2"]),
        )
    return resolved or zone.fields
