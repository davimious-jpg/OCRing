from __future__ import annotations

from ocring.ocr.capture_loss import CaptureLossMonitor, CaptureLossState


def test_capture_loss_detects_window_loss_and_resume() -> None:
    monitor = CaptureLossMonitor()

    state = monitor.evaluate(window_present=False)
    assert state is CaptureLossState.WINDOW_LOST
    assert monitor.paused is True

    resumed = monitor.resume()
    assert resumed is CaptureLossState.CAPTURE_ACTIVE
    assert monitor.paused is False

