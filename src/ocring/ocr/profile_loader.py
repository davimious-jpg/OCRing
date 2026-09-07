from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ocring.ui.notification import NotificationCenter, NotificationRecord, NotificationSeverity

from .profile import DEFAULT_PROFILES_ROOT, Profile, load_profile


class ProfileTrustLevel(str, Enum):
    BUILT_IN = "BUILT_IN"
    USER_CREATED = "USER_CREATED"
    COMMUNITY_UNVERIFIED = "COMMUNITY_UNVERIFIED"
    COMMUNITY_VERIFIED = "COMMUNITY_VERIFIED"


@dataclass(frozen=True)
class LoadedProfile:
    profile: Profile
    trust_level: ProfileTrustLevel
    notification: NotificationRecord | None = None


def load_profile_with_trust(
    profile_id: str,
    *,
    profiles_root: Path = DEFAULT_PROFILES_ROOT,
    allow_unverified: bool = False,
    notification_center: NotificationCenter | None = None,
) -> LoadedProfile:
    payload = _read_profile_payload(profile_id, profiles_root=profiles_root)
    trust_level = _coerce_trust_level(payload.get("profile_trust_level"))
    notification: NotificationRecord | None = None
    if trust_level is ProfileTrustLevel.COMMUNITY_UNVERIFIED:
        center = notification_center or NotificationCenter()
        notification = center.notify(
            NotificationSeverity.WARNING,
            f"Profile '{profile_id}' is COMMUNITY_UNVERIFIED and requires explicit confirmation before loading.",
        )
        if not allow_unverified:
            raise PermissionError(
                f"Profile '{profile_id}' is COMMUNITY_UNVERIFIED; explicit confirmation is required before loading."
            )
    profile = load_profile(profile_id, profiles_root=profiles_root)
    return LoadedProfile(profile=profile, trust_level=trust_level, notification=notification)


def _read_profile_payload(profile_id: str, *, profiles_root: Path) -> dict[str, object]:
    path = profiles_root / profile_id / "profile.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_trust_level(value: object) -> ProfileTrustLevel:
    text = str(value or ProfileTrustLevel.USER_CREATED.value).strip().upper()
    try:
        return ProfileTrustLevel(text)
    except ValueError:
        return ProfileTrustLevel.USER_CREATED
