from __future__ import annotations

from pathlib import Path

from PIL import Image

from ocring.ocr.capture_backend import (
    CaptureTargetIdentity,
    CaptureBackendKind,
    CaptureStatus,
    DesktopDuplication,
    RegionScreenshotFallback,
    WindowDescriptor,
    WindowsGraphicsCapture,
    find_reacquisition_candidate,
    validate_capture_surface,
)
from ocring.ocr.privacy_policy import PrivacyPolicy


def test_capture_backend_abstraction_exposes_expected_backends() -> None:
    window = WindowsGraphicsCapture().capture()
    desktop = DesktopDuplication().capture()
    region = RegionScreenshotFallback().capture()

    assert window.backend is CaptureBackendKind.WINDOWS_GRAPHICS_CAPTURE
    assert desktop.backend is CaptureBackendKind.DESKTOP_DUPLICATION
    assert region.backend is CaptureBackendKind.REGION_SCREENSHOT_FALLBACK


def test_capture_backend_keeps_capturing_when_target_window_loses_focus(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    monkeypatch.setattr(
        capture_backend_module,
        "_capture_window_image",
        lambda window: capture_backend_module.CapturedImage(
            capture_backend_module.Path("frame.png"),
            1280,
            720,
            window.capture_rect(),
        ),
    )
    monkeypatch.setattr(
        capture_backend_module,
        "get_window_descriptor",
        lambda handle: WindowDescriptor(int(handle), "Defiance", 0, 0, 1280, 720, True, False),
    )

    unfocused = WindowsGraphicsCapture().capture(
        target_window_handle=101,
        foreground_window_handle=404,
        target_visible=True,
    )

    assert unfocused.status is CaptureStatus.CAPTURE_ACTIVE
    assert unfocused.reason == ""


def test_capture_backend_pauses_when_target_window_is_hidden() -> None:
    frame = DesktopDuplication().capture(
        target_window_handle=202,
        foreground_window_handle=202,
        target_visible=False,
    )

    assert frame.status is CaptureStatus.CAPTURE_PAUSED
    assert frame.reason == "TARGET_WINDOW_NOT_VISIBLE"


def test_capture_backend_exposes_debug_capture_opt_in_state() -> None:
    disabled = WindowsGraphicsCapture().capture(
        target_window_handle=1,
        foreground_window_handle=1,
        target_visible=True,
        privacy_policy=PrivacyPolicy(debug_capture_opt_in=False),
    )
    enabled = WindowsGraphicsCapture().capture(
        target_window_handle=1,
        foreground_window_handle=1,
        target_visible=True,
        privacy_policy=PrivacyPolicy(debug_capture_opt_in=True),
    )

    assert disabled.debug_capture_enabled is False
    assert enabled.debug_capture_enabled is True


def test_capture_backend_does_not_pause_for_window_geometry_changes(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    geometries = [
        WindowDescriptor(101, "Defiance", 0, 0, 1280, 720, True, True),
        WindowDescriptor(101, "Defiance", 40, 20, 1320, 740, True, True),
        WindowDescriptor(101, "Defiance", 40, 20, 1320, 740, True, True),
    ]
    geometry_iter = iter(geometries)

    monkeypatch.setattr(capture_backend_module, "get_window_descriptor", lambda handle: next(geometry_iter))
    monkeypatch.setattr(
        capture_backend_module,
        "_capture_window_image",
        lambda window: capture_backend_module.CapturedImage(
            capture_backend_module.Path("frame.png"),
            window.width,
            window.height,
            window.capture_rect(),
        ),
    )

    first = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=101, target_visible=True)
    second = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=101, target_visible=True)
    third = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=101, target_visible=True)

    assert first.status is CaptureStatus.CAPTURE_ACTIVE
    assert second.status is CaptureStatus.CAPTURE_ACTIVE
    assert third.status is CaptureStatus.CAPTURE_ACTIVE


def test_capture_backend_rejects_tiny_collapsed_capture_surface(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    tiny = WindowDescriptor(101, "Defiance", 0, 0, 156, 24, True, True)
    monkeypatch.setattr(capture_backend_module, "get_window_descriptor", lambda handle: tiny)

    called = {"count": 0}

    def fake_capture_window_image(window):
        called["count"] += 1
        del window
        return None

    monkeypatch.setattr(capture_backend_module, "_capture_window_image", fake_capture_window_image)

    frame = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=101, target_visible=True)

    assert frame.status is CaptureStatus.CAPTURE_PAUSED
    assert frame.reason == "CAPTURE_WIDTH_TOO_SMALL"
    assert called["count"] == 0


def test_capture_backend_accepts_legitimate_alternative_resolution(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    window = WindowDescriptor(101, "Defiance", 0, 0, 1024, 768, True, True)
    monkeypatch.setattr(capture_backend_module, "get_window_descriptor", lambda handle: window)
    monkeypatch.setattr(
        capture_backend_module,
        "_capture_window_image",
        lambda surface: capture_backend_module.CapturedImage(capture_backend_module.Path("frame.png"), 1024, 768, surface.capture_rect()),
    )

    frame = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=101, target_visible=True)

    assert frame.status is CaptureStatus.CAPTURE_ACTIVE
    assert frame.width == 1024
    assert frame.height == 768


def test_capture_backend_reacquires_matching_replacement_window(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    replacement = WindowDescriptor(
        202,
        "Defiance",
        0,
        0,
        1280,
        720,
        True,
        False,
        class_name="LaunchUnrealUWindowsClient",
        pid=4242,
    )
    monkeypatch.setattr(capture_backend_module, "get_window_descriptor", lambda handle: None)
    monkeypatch.setattr(capture_backend_module, "list_available_windows", lambda: [replacement])
    monkeypatch.setattr(
        capture_backend_module,
        "_capture_window_image",
        lambda surface: capture_backend_module.CapturedImage(capture_backend_module.Path("frame.png"), 1280, 720, surface.capture_rect()),
    )

    frame = RegionScreenshotFallback().capture(
        target_window_handle=101,
        foreground_window_handle=404,
        target_visible=True,
        target_identity=CaptureTargetIdentity(selected_handle=101, title="Defiance", class_name="LaunchUnrealUWindowsClient", pid=4242),
    )

    assert frame.status is CaptureStatus.CAPTURE_ACTIVE
    assert frame.window_handle == 202
    assert frame.capture_metadata["reacquired_from_handle"] == 101
    assert frame.capture_metadata["reacquired_to_handle"] == 202


def test_capture_backend_reports_frame_capture_failure_when_image_grab_fails(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    monkeypatch.setattr(
        capture_backend_module,
        "get_window_descriptor",
        lambda handle: WindowDescriptor(int(handle), "Defiance", 0, 0, 1280, 720, True, True),
    )
    monkeypatch.setattr(capture_backend_module, "_capture_window_image", lambda window: None)

    frame = RegionScreenshotFallback().capture(target_window_handle=101, foreground_window_handle=404, target_visible=True)

    assert frame.status is CaptureStatus.CAPTURE_PAUSED
    assert frame.reason == "FRAME_CAPTURE_FAILED"


def test_capture_backend_writes_unique_atomic_png_files(tmp_path: Path, monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    monkeypatch.setattr(capture_backend_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(capture_backend_module, "ImageGrab", None, raising=False)

    window = WindowDescriptor(101, "Defiance", 0, 0, 64, 64, True, True)
    image = Image.new("RGB", (64, 64), (25, 50, 75))
    class _FakeImageGrab:
        @staticmethod
        def grab(*args, **kwargs):
            del args, kwargs
            return image

    import sys
    import types

    sys.modules["PIL.ImageGrab"] = types.SimpleNamespace(grab=_FakeImageGrab.grab)

    first = capture_backend_module._capture_window_image(window)
    second = capture_backend_module._capture_window_image(window)

    assert first is not None
    assert second is not None
    first_path, first_width, first_height = first.output_path, first.width, first.height
    second_path, second_width, second_height = second.output_path, second.width, second.height

    assert first_width == 64
    assert first_height == 64
    assert second_width == 64
    assert second_height == 64
    assert first_path != second_path
    assert first_path.exists()
    assert second_path.exists()
    assert first_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert second_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not list(tmp_path.rglob("*.tmp"))


def test_validate_capture_surface_flags_invalid_aspect_and_size() -> None:
    tiny = WindowDescriptor(101, "Defiance", 0, 0, 156, 24, True, True)
    tall = WindowDescriptor(101, "Defiance", 0, 0, 500, 900, True, True)
    normal = WindowDescriptor(101, "Defiance", 0, 0, 1280, 720, True, True)

    assert validate_capture_surface(tiny).valid is False
    assert validate_capture_surface(tall).reason == "CAPTURE_WIDTH_TOO_SMALL"
    assert validate_capture_surface(normal).valid is True


def test_find_reacquisition_candidate_requires_matching_identity(monkeypatch) -> None:
    from ocring.ocr import capture_backend as capture_backend_module

    matching = WindowDescriptor(202, "Defiance", 0, 0, 1280, 720, True, False, class_name="LaunchUnrealUWindowsClient", pid=777)
    unrelated = WindowDescriptor(303, "Defiance Wiki", 0, 0, 1280, 720, True, False, class_name="Chrome_WidgetWin_1", pid=888)
    monkeypatch.setattr(capture_backend_module, "list_available_windows", lambda: [unrelated, matching])

    candidate = find_reacquisition_candidate(
        CaptureTargetIdentity(selected_handle=101, title="Defiance", class_name="LaunchUnrealUWindowsClient", pid=777)
    )

    assert candidate is not None
    assert candidate.handle == 202
