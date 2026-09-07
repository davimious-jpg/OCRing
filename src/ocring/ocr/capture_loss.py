from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CaptureLossState(str, Enum):
    CAPTURE_ACTIVE = "CAPTURE_ACTIVE"
    CAPTURE_STALLED = "CAPTURE_STALLED"
    WINDOW_LOST = "WINDOW_LOST"
    WINDOW_MINIMIZED = "WINDOW_MINIMIZED"
    PROFILE_MISMATCH = "PROFILE_MISMATCH"
    RESOLUTION_CHANGED = "RESOLUTION_CHANGED"


@dataclass
class CaptureLossMonitor:
    state: CaptureLossState = CaptureLossState.CAPTURE_ACTIVE
    paused: bool = False

    def evaluate(
        self,
        *,
        stalled: bool = False,
        window_present: bool = True,
        minimized: bool = False,
        profile_matches: bool = True,
        resolution_changed: bool = False,
    ) -> CaptureLossState:
        if not window_present:
            self.state = CaptureLossState.WINDOW_LOST
        elif minimized:
            self.state = CaptureLossState.WINDOW_MINIMIZED
        elif not profile_matches:
            self.state = CaptureLossState.PROFILE_MISMATCH
        elif resolution_changed:
            self.state = CaptureLossState.RESOLUTION_CHANGED
        elif stalled:
            self.state = CaptureLossState.CAPTURE_STALLED
        else:
            self.state = CaptureLossState.CAPTURE_ACTIVE
        self.paused = self.state is not CaptureLossState.CAPTURE_ACTIVE
        return self.state

    def resume(self) -> CaptureLossState:
        self.state = CaptureLossState.CAPTURE_ACTIVE
        self.paused = False
        return self.state

