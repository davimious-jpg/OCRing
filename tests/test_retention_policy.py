from __future__ import annotations

from ocring.ocr.retention_policy import default_retention_policy


def test_retention_policy_declares_expected_rules() -> None:
    policy = default_retention_policy()

    assert policy.raw_video_frames_seconds == 30
    assert policy.best_evidence_crops == "until_resolved"
    assert policy.accepted_provenance == "long-term-optional"
    assert policy.api_payloads == "discard-after-response"

