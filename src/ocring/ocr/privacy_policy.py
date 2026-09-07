from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrivacyPolicy:
    capture_target_window_only: bool = True
    never_capture_unrelated_monitors: bool = True
    api_receives_crop_only: bool = True
    temporary_frames_auto_expire: bool = True
    debug_capture_opt_in: bool = True

    def evaluate_capture_state(self, *, target_window_present: bool) -> str:
        if not target_window_present:
            return "CAPTURE_PAUSED"
        return "CAPTURE_ALLOWED"

