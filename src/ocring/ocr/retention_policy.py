from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    raw_video_frames_seconds: int
    best_evidence_crops: str
    accepted_provenance: str
    full_screenshots: str
    api_payloads: str


def default_retention_policy(*, full_screenshots: str = "user-configurable") -> RetentionPolicy:
    return RetentionPolicy(
        raw_video_frames_seconds=30,
        best_evidence_crops="until_resolved",
        accepted_provenance="long-term-optional",
        full_screenshots=full_screenshots,
        api_payloads="discard-after-response",
    )

