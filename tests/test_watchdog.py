from __future__ import annotations

from ocring.ocr.watchdog import WatchdogAction, WorkerWatchdog


def test_watchdog_retries_then_isolates_timeout_jobs() -> None:
    watchdog = WorkerWatchdog(timeout_seconds=2.0)

    retry = watchdog.evaluate(elapsed_seconds=3.0, retry_count=0)
    isolate = watchdog.evaluate(elapsed_seconds=3.0, retry_count=1)

    assert retry.action is WatchdogAction.RETRY
    assert retry.keep_capture_alive is True
    assert isolate.action is WatchdogAction.ISOLATE

