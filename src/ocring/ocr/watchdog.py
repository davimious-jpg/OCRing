from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WatchdogAction(str, Enum):
    HEALTHY = "HEALTHY"
    RETRY = "RETRY"
    ISOLATE = "ISOLATE"


@dataclass(frozen=True)
class WatchdogResult:
    action: WatchdogAction
    release_evidence: bool
    keep_capture_alive: bool


class WorkerWatchdog:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def evaluate(self, *, elapsed_seconds: float, retry_count: int) -> WatchdogResult:
        if elapsed_seconds <= self.timeout_seconds:
            return WatchdogResult(WatchdogAction.HEALTHY, False, True)
        if retry_count < 1:
            return WatchdogResult(WatchdogAction.RETRY, True, True)
        return WatchdogResult(WatchdogAction.ISOLATE, True, True)

