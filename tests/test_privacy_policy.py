from __future__ import annotations

from ocring.ocr.privacy_policy import PrivacyPolicy


def test_privacy_policy_emits_capture_paused_when_target_missing() -> None:
    policy = PrivacyPolicy()

    assert policy.capture_target_window_only is True
    assert policy.never_capture_unrelated_monitors is True
    assert policy.evaluate_capture_state(target_window_present=False) == "CAPTURE_PAUSED"

