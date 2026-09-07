from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from uuid import uuid4


@dataclass(frozen=True)
class FrameIdentity:
    frame_id: str
    capture_timestamp: str
    session_id: str
    window_id: str
    profile_version: str
    region_id: str
    monotonic_time: float

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        window_id: str,
        profile_version: str,
        region_id: str,
        frame_id: str | None = None,
        capture_timestamp: str | None = None,
        monotonic_time: float | None = None,
    ) -> FrameIdentity:
        return cls(
            frame_id=frame_id or str(uuid4()),
            capture_timestamp=capture_timestamp or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            session_id=session_id,
            window_id=window_id,
            profile_version=profile_version,
            region_id=region_id,
            monotonic_time=monotonic_time if monotonic_time is not None else time.monotonic(),
        )


class PipelineClock:
    def now(self) -> float:
        return time.monotonic()

