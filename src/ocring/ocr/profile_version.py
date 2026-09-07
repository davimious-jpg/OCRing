from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .profile import DEFAULT_PROFILES_ROOT, load_profile


@dataclass(frozen=True)
class ProfileVersion:
    profile_id: str
    profile_version: str
    scan_timestamp: str

    @classmethod
    def for_scan(
        cls,
        profile_id: str,
        *,
        scan_timestamp: str | None = None,
        profiles_root: Path = DEFAULT_PROFILES_ROOT,
    ) -> "ProfileVersion":
        try:
            profile = load_profile(profile_id, profiles_root=profiles_root)
            version = str(profile.version or "1")
        except OSError:
            version = "1"
        return cls(
            profile_id=profile_id,
            profile_version=version,
            scan_timestamp=scan_timestamp or datetime.now(timezone.utc).isoformat(),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "scan_timestamp": self.scan_timestamp,
        }
