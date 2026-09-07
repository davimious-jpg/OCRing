from __future__ import annotations

import json
from pathlib import Path

from ocring.ocr.profile import create_default_template, save_profile
from ocring.ocr.profile_loader import ProfileTrustLevel, load_profile_with_trust
from ocring.ui.notification import NotificationCenter, NotificationSeverity


def test_profile_loader_requires_confirmation_for_unverified_community_profiles(tmp_path: Path) -> None:
    profile = create_default_template()
    save_path = save_profile(profile, profiles_root=tmp_path)
    payload = json.loads(save_path.read_text(encoding="utf-8"))
    payload["profile_trust_level"] = "COMMUNITY_UNVERIFIED"
    save_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    center = NotificationCenter()

    try:
        load_profile_with_trust(profile.profile_id, profiles_root=tmp_path, notification_center=center)
    except PermissionError:
        pass
    else:
        raise AssertionError("expected community-unverified profile to require confirmation")

    assert center.history()
    assert center.history()[0].severity is NotificationSeverity.WARNING


def test_profile_loader_allows_explicitly_confirmed_unverified_profile(tmp_path: Path) -> None:
    profile = create_default_template()
    save_path = save_profile(profile, profiles_root=tmp_path)
    payload = json.loads(save_path.read_text(encoding="utf-8"))
    payload["profile_trust_level"] = "COMMUNITY_UNVERIFIED"
    save_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    loaded = load_profile_with_trust(profile.profile_id, profiles_root=tmp_path, allow_unverified=True)

    assert loaded.profile.profile_id == profile.profile_id
    assert loaded.trust_level is ProfileTrustLevel.COMMUNITY_UNVERIFIED
    assert loaded.notification is not None

