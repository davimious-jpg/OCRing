from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .profile import DEFAULT_PROFILES_ROOT


@dataclass
class GenericProfile:
    profile_id: str
    profile_name: str
    version: str
    custom_fields: list[dict[str, str]] = field(default_factory=list)
    region_roi: dict[str, int] = field(default_factory=dict)
    scan_scope: str = "FULL_INVENTORY"
    generic_session_id: str = ""
    profile_kind: str = "generic"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_generic_profile(
    name: str,
    region_roi: tuple[int, int, int, int],
    fields: list[dict[str, str]],
    *,
    scan_scope: str = "FULL_INVENTORY",
    generic_session_id: str | None = None,
) -> GenericProfile:
    limited_fields = [dict(field) for field in fields[:5]]
    profile_id = f"generic-{uuid4().hex[:8]}"
    return GenericProfile(
        profile_id=profile_id,
        profile_name=name.strip() or profile_id,
        version="1",
        custom_fields=limited_fields,
        region_roi={
            "x1": int(region_roi[0]),
            "y1": int(region_roi[1]),
            "x2": int(region_roi[2]),
            "y2": int(region_roi[3]),
        },
        scan_scope=scan_scope,
        generic_session_id=generic_session_id or f"session-{uuid4().hex[:8]}",
    )


def save_generic_profile(profile: GenericProfile, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> Path:
    profile_dir = profiles_root / profile.profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "profile.json"
    profile_path.write_text(json.dumps(profile.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return profile_path


def load_generic_profile(profile_id: str, *, profiles_root: Path = DEFAULT_PROFILES_ROOT) -> GenericProfile:
    path = profiles_root / profile_id / "profile.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    region_roi = payload.get("region_roi") or {}
    return GenericProfile(
        profile_id=str(payload.get("profile_id") or profile_id),
        profile_name=str(payload.get("profile_name") or profile_id),
        version=str(payload.get("version") or "1"),
        custom_fields=_as_field_list(payload.get("custom_fields")),
        region_roi={
            "x1": int(region_roi.get("x1", 0)),
            "y1": int(region_roi.get("y1", 0)),
            "x2": int(region_roi.get("x2", 0)),
            "y2": int(region_roi.get("y2", 0)),
        },
        scan_scope=str(payload.get("scan_scope") or "FULL_INVENTORY"),
        generic_session_id=str(payload.get("generic_session_id") or ""),
        profile_kind="generic",
    )


def _as_field_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    fields: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        fields.append(
            {
                "field_name": str(item.get("field_name") or ""),
                "field_type": str(item.get("field_type") or "text"),
                "field_source": str(item.get("field_source") or ""),
            }
        )
    return fields
