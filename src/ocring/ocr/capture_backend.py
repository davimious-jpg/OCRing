from __future__ import annotations

import ctypes
import os
import tempfile
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from .privacy_policy import PrivacyPolicy


class CaptureBackendKind(str, Enum):
    WINDOWS_GRAPHICS_CAPTURE = "WindowsGraphicsCapture"
    DESKTOP_DUPLICATION = "DesktopDuplication"
    REGION_SCREENSHOT_FALLBACK = "RegionScreenshotFallback"


class CaptureStatus(str, Enum):
    CAPTURE_ACTIVE = "CAPTURE_ACTIVE"
    CAPTURE_PAUSED = "CAPTURE_PAUSED"


@dataclass(frozen=True)
class CaptureFrame:
    backend: CaptureBackendKind
    width: int
    height: int
    source: str
    status: CaptureStatus = CaptureStatus.CAPTURE_ACTIVE
    reason: str = ""
    debug_capture_enabled: bool = True
    image_path: str = ""
    window_handle: int = 0
    window_title: str = ""
    capture_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowDescriptor:
    handle: int
    title: str
    left: int
    top: int
    right: int
    bottom: int
    is_visible: bool
    is_foreground: bool
    class_name: str = ""
    pid: int = 0
    parent_handle: int = 0
    owner_handle: int = 0
    is_iconic: bool = False
    client_left: int = 0
    client_top: int = 0
    client_right: int = 0
    client_bottom: int = 0
    client_screen_left: int = 0
    client_screen_top: int = 0
    client_screen_right: int = 0
    client_screen_bottom: int = 0
    dwm_left: int = 0
    dwm_top: int = 0
    dwm_right: int = 0
    dwm_bottom: int = 0

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def client_width(self) -> int:
        return max(0, self.client_right - self.client_left)

    @property
    def client_height(self) -> int:
        return max(0, self.client_bottom - self.client_top)

    @property
    def client_screen_width(self) -> int:
        return max(0, self.client_screen_right - self.client_screen_left)

    @property
    def client_screen_height(self) -> int:
        return max(0, self.client_screen_bottom - self.client_screen_top)

    def geometry_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def capture_rect(self) -> tuple[int, int, int, int]:
        if self.client_screen_width > 0 and self.client_screen_height > 0:
            return (
                self.client_screen_left,
                self.client_screen_top,
                self.client_screen_right,
                self.client_screen_bottom,
            )
        return self.geometry_tuple()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "hwnd": self.handle,
            "title": self.title,
            "class_name": self.class_name,
            "pid": self.pid,
            "parent_hwnd": self.parent_handle,
            "owner_hwnd": self.owner_handle,
            "visible": self.is_visible,
            "foreground": self.is_foreground,
            "iconic": self.is_iconic,
            "window_rect": {
                "left": self.left,
                "top": self.top,
                "right": self.right,
                "bottom": self.bottom,
                "width": self.width,
                "height": self.height,
            },
            "client_rect": {
                "left": self.client_left,
                "top": self.client_top,
                "right": self.client_right,
                "bottom": self.client_bottom,
                "width": self.client_width,
                "height": self.client_height,
            },
            "client_screen_rect": {
                "left": self.client_screen_left,
                "top": self.client_screen_top,
                "right": self.client_screen_right,
                "bottom": self.client_screen_bottom,
                "width": self.client_screen_width,
                "height": self.client_screen_height,
            },
            "dwm_extended_frame_bounds": (
                {
                    "left": self.dwm_left,
                    "top": self.dwm_top,
                    "right": self.dwm_right,
                    "bottom": self.dwm_bottom,
                    "width": max(0, self.dwm_right - self.dwm_left),
                    "height": max(0, self.dwm_bottom - self.dwm_top),
                }
                if any((self.dwm_left, self.dwm_top, self.dwm_right, self.dwm_bottom))
                else None
            ),
        }


@dataclass(frozen=True)
class CaptureTargetIdentity:
    selected_handle: int
    title: str = ""
    class_name: str = ""
    pid: int = 0

    @classmethod
    def from_window(cls, window: WindowDescriptor) -> "CaptureTargetIdentity":
        return cls(
            selected_handle=window.handle,
            title=window.title,
            class_name=window.class_name,
            pid=window.pid,
        )


@dataclass(frozen=True)
class CaptureSurfaceCheck:
    valid: bool
    reason: str = ""


@dataclass(frozen=True)
class CapturedImage:
    output_path: Path
    width: int
    height: int
    capture_rect: tuple[int, int, int, int]


class CaptureBackend(Protocol):
    kind: CaptureBackendKind

    def capture(
        self,
        target_window_handle: int | None = None,
        *,
        foreground_window_handle: int | None = None,
        target_visible: bool = True,
        privacy_policy: PrivacyPolicy | None = None,
        target_identity: CaptureTargetIdentity | None = None,
    ) -> CaptureFrame:
        ...


_USER32 = ctypes.windll.user32
_DWM_EXTENDED_FRAME_BOUNDS = 9
_GW_OWNER = 4
_MIN_GAMEPLAY_WIDTH = 640
_MIN_GAMEPLAY_HEIGHT = 360
_MIN_GAMEPLAY_ASPECT = 1.2
_MAX_GAMEPLAY_ASPECT = 3.6


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def list_available_windows() -> list[WindowDescriptor]:
    windows: list[WindowDescriptor] = []
    foreground = get_foreground_window_handle()

    def callback(hwnd: int, _lparam: int) -> bool:
        if not _USER32.IsWindowVisible(hwnd):
            return True
        title = _window_text(int(hwnd))
        if not title:
            return True
        window = describe_window(int(hwnd), foreground_window_handle=foreground, known_title=title)
        if window is not None:
            windows.append(window)
        return True

    _USER32.EnumWindows(EnumWindowsProc(callback), 0)
    return sorted(windows, key=lambda item: item.title.lower())


def get_foreground_window_handle() -> int:
    return int(_USER32.GetForegroundWindow())


def get_window_descriptor(window_handle: int) -> WindowDescriptor | None:
    return describe_window(int(window_handle))


def describe_window(
    window_handle: int,
    *,
    foreground_window_handle: int | None = None,
    known_title: str | None = None,
) -> WindowDescriptor | None:
    hwnd = int(window_handle or 0)
    if hwnd <= 0 or not _USER32.IsWindow(hwnd):
        return None

    rect = _RECT()
    if not _USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None

    client_rect = _RECT()
    _USER32.GetClientRect(hwnd, ctypes.byref(client_rect))
    origin = _POINT(int(client_rect.left), int(client_rect.top))
    if _USER32.ClientToScreen(hwnd, ctypes.byref(origin)):
        client_screen_left = int(origin.x)
        client_screen_top = int(origin.y)
    else:
        client_screen_left = int(rect.left)
        client_screen_top = int(rect.top)

    client_width = max(0, int(client_rect.right - client_rect.left))
    client_height = max(0, int(client_rect.bottom - client_rect.top))
    pid = wintypes.DWORD()
    _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    class_buffer = ctypes.create_unicode_buffer(256)
    _USER32.GetClassNameW(hwnd, class_buffer, 255)
    title = str(known_title or _window_text(hwnd))
    dwm_rect = _read_dwm_extended_frame_bounds(hwnd)
    parent_handle = int(_USER32.GetParent(hwnd) or 0)
    owner_handle = int(_USER32.GetWindow(hwnd, _GW_OWNER) or 0)
    foreground = get_foreground_window_handle() if foreground_window_handle is None else int(foreground_window_handle)

    return WindowDescriptor(
        handle=hwnd,
        title=title,
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
        is_visible=bool(_USER32.IsWindowVisible(hwnd)),
        is_foreground=hwnd == foreground,
        class_name=class_buffer.value,
        pid=int(pid.value),
        parent_handle=parent_handle,
        owner_handle=owner_handle,
        is_iconic=bool(_USER32.IsIconic(hwnd)),
        client_left=int(client_rect.left),
        client_top=int(client_rect.top),
        client_right=int(client_rect.right),
        client_bottom=int(client_rect.bottom),
        client_screen_left=client_screen_left,
        client_screen_top=client_screen_top,
        client_screen_right=client_screen_left + client_width,
        client_screen_bottom=client_screen_top + client_height,
        dwm_left=int(dwm_rect.left) if dwm_rect is not None else 0,
        dwm_top=int(dwm_rect.top) if dwm_rect is not None else 0,
        dwm_right=int(dwm_rect.right) if dwm_rect is not None else 0,
        dwm_bottom=int(dwm_rect.bottom) if dwm_rect is not None else 0,
    )


def find_reacquisition_candidate(target_identity: CaptureTargetIdentity) -> WindowDescriptor | None:
    candidates: list[tuple[int, int, WindowDescriptor]] = []
    normalized_title = str(target_identity.title or "").strip().lower()
    normalized_class = str(target_identity.class_name or "").strip().lower()
    for window in list_available_windows():
        if not window.is_visible or window.is_iconic:
            continue
        score = 0
        if target_identity.pid and window.pid == target_identity.pid:
            score += 5
        if normalized_class and window.class_name.strip().lower() == normalized_class:
            score += 4
        candidate_title = window.title.strip().lower()
        if normalized_title and candidate_title == normalized_title:
            score += 4
        elif normalized_title and normalized_title in candidate_title:
            score += 2
        if score <= 0:
            continue
        surface_check = validate_capture_surface(window)
        if not surface_check.valid:
            continue
        candidates.append((score, window.width * window.height, window))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2].handle), reverse=True)
    return candidates[0][2]


@dataclass(frozen=True)
class WindowsGraphicsCapture:
    width: int = 1920
    height: int = 1080
    kind: CaptureBackendKind = CaptureBackendKind.WINDOWS_GRAPHICS_CAPTURE

    def capture(
        self,
        target_window_handle: int | None = None,
        *,
        foreground_window_handle: int | None = None,
        target_visible: bool = True,
        privacy_policy: PrivacyPolicy | None = None,
        target_identity: CaptureTargetIdentity | None = None,
    ) -> CaptureFrame:
        return _capture_with_target_checks(
            self.kind,
            self.width,
            self.height,
            "window",
            target_window_handle=target_window_handle,
            foreground_window_handle=foreground_window_handle,
            target_visible=target_visible,
            privacy_policy=privacy_policy or PrivacyPolicy(),
            target_identity=target_identity,
        )


@dataclass(frozen=True)
class DesktopDuplication:
    width: int = 1920
    height: int = 1080
    kind: CaptureBackendKind = CaptureBackendKind.DESKTOP_DUPLICATION

    def capture(
        self,
        target_window_handle: int | None = None,
        *,
        foreground_window_handle: int | None = None,
        target_visible: bool = True,
        privacy_policy: PrivacyPolicy | None = None,
        target_identity: CaptureTargetIdentity | None = None,
    ) -> CaptureFrame:
        return _capture_with_target_checks(
            self.kind,
            self.width,
            self.height,
            "desktop",
            target_window_handle=target_window_handle,
            foreground_window_handle=foreground_window_handle,
            target_visible=target_visible,
            privacy_policy=privacy_policy or PrivacyPolicy(),
            target_identity=target_identity,
        )


@dataclass(frozen=True)
class RegionScreenshotFallback:
    width: int = 1280
    height: int = 720
    kind: CaptureBackendKind = CaptureBackendKind.REGION_SCREENSHOT_FALLBACK

    def capture(
        self,
        target_window_handle: int | None = None,
        *,
        foreground_window_handle: int | None = None,
        target_visible: bool = True,
        privacy_policy: PrivacyPolicy | None = None,
        target_identity: CaptureTargetIdentity | None = None,
    ) -> CaptureFrame:
        return _capture_with_target_checks(
            self.kind,
            self.width,
            self.height,
            "region",
            target_window_handle=target_window_handle,
            foreground_window_handle=foreground_window_handle,
            target_visible=target_visible,
            privacy_policy=privacy_policy or PrivacyPolicy(),
            target_identity=target_identity,
        )


def _capture_with_target_checks(
    backend: CaptureBackendKind,
    width: int,
    height: int,
    source: str,
    *,
    target_window_handle: int | None,
    foreground_window_handle: int | None,
    target_visible: bool,
    privacy_policy: PrivacyPolicy,
    target_identity: CaptureTargetIdentity | None,
) -> CaptureFrame:
    selected_handle = int(target_window_handle or 0)
    metadata: dict[str, Any] = {
        "selected_window_handle": selected_handle,
        "foreground_window_handle": int(foreground_window_handle or 0),
        "target_identity": (
            {
                "title": target_identity.title,
                "class_name": target_identity.class_name,
                "pid": target_identity.pid,
            }
            if target_identity is not None
            else None
        ),
    }

    window = get_window_descriptor(selected_handle) if selected_handle not in {0} else None
    metadata["resolved_window"] = window.as_metadata() if window is not None else None
    if window is None and target_identity is not None:
        replacement = find_reacquisition_candidate(target_identity)
        if replacement is not None:
            metadata["reacquired_from_handle"] = selected_handle or None
            metadata["reacquired_to_handle"] = replacement.handle
            window = replacement
            metadata["resolved_window"] = replacement.as_metadata()

    resolved_visible = bool(target_visible)
    if window is not None:
        resolved_visible = resolved_visible and window.is_visible and window.width > 0 and window.height > 0

    if selected_handle not in {0} or window is not None:
        if not target_visible:
            return CaptureFrame(
                backend,
                width,
                height,
                source,
                status=CaptureStatus.CAPTURE_PAUSED,
                reason="TARGET_WINDOW_NOT_VISIBLE",
                debug_capture_enabled=privacy_policy.debug_capture_opt_in,
                window_handle=int(window.handle if window is not None else selected_handle),
                window_title=window.title if window is not None else "",
                capture_metadata=metadata,
            )
        if not resolved_visible:
            return CaptureFrame(
                backend,
                width,
                height,
                source,
                status=CaptureStatus.CAPTURE_PAUSED,
                reason="TARGET_WINDOW_NOT_VISIBLE",
                debug_capture_enabled=privacy_policy.debug_capture_opt_in,
                window_handle=int(window.handle if window is not None else selected_handle),
                window_title=window.title if window is not None else "",
                capture_metadata=metadata,
            )

        surface_check = validate_capture_surface(window)
        metadata["surface_check"] = {"valid": surface_check.valid, "reason": surface_check.reason}
        if not surface_check.valid and target_identity is not None and window is not None:
            replacement = find_reacquisition_candidate(target_identity)
            if replacement is not None and replacement.handle != window.handle:
                metadata["reacquired_from_handle"] = window.handle
                metadata["reacquired_to_handle"] = replacement.handle
                window = replacement
                metadata["resolved_window"] = replacement.as_metadata()
                surface_check = validate_capture_surface(window)
                metadata["surface_check"] = {"valid": surface_check.valid, "reason": surface_check.reason}

        if not surface_check.valid:
            return CaptureFrame(
                backend,
                max(0, window.capture_rect()[2] - window.capture_rect()[0]) if window is not None else width,
                max(0, window.capture_rect()[3] - window.capture_rect()[1]) if window is not None else height,
                source,
                status=CaptureStatus.CAPTURE_PAUSED,
                reason=surface_check.reason or "INVALID_CAPTURE_SURFACE",
                debug_capture_enabled=privacy_policy.debug_capture_opt_in,
                window_handle=int(window.handle if window is not None else selected_handle),
                window_title=window.title if window is not None else "",
                capture_metadata=metadata,
            )

        screenshot = _capture_window_image(window)
        if screenshot is None:
            return CaptureFrame(
                backend,
                width,
                height,
                source,
                status=CaptureStatus.CAPTURE_PAUSED,
                reason="FRAME_CAPTURE_FAILED",
                debug_capture_enabled=privacy_policy.debug_capture_opt_in,
                window_handle=int(window.handle if window is not None else selected_handle),
                window_title=window.title if window is not None else "",
                capture_metadata=metadata,
            )

        metadata["capture_rect"] = {
            "left": screenshot.capture_rect[0],
            "top": screenshot.capture_rect[1],
            "right": screenshot.capture_rect[2],
            "bottom": screenshot.capture_rect[3],
            "width": screenshot.capture_rect[2] - screenshot.capture_rect[0],
            "height": screenshot.capture_rect[3] - screenshot.capture_rect[1],
        }
        metadata["returned_image_size"] = {"width": screenshot.width, "height": screenshot.height}
        returned_surface = validate_captured_dimensions(screenshot.width, screenshot.height)
        metadata["returned_surface_check"] = {"valid": returned_surface.valid, "reason": returned_surface.reason}
        if not returned_surface.valid:
            return CaptureFrame(
                backend,
                screenshot.width,
                screenshot.height,
                source,
                status=CaptureStatus.CAPTURE_PAUSED,
                reason=returned_surface.reason or "INVALID_CAPTURE_SURFACE",
                debug_capture_enabled=privacy_policy.debug_capture_opt_in,
                window_handle=int(window.handle if window is not None else selected_handle),
                window_title=window.title if window is not None else "",
                capture_metadata=metadata,
            )

        return CaptureFrame(
            backend,
            screenshot.width,
            screenshot.height,
            source,
            status=CaptureStatus.CAPTURE_ACTIVE,
            debug_capture_enabled=privacy_policy.debug_capture_opt_in,
            image_path=str(screenshot.output_path),
            window_handle=int(window.handle if window is not None else selected_handle),
            window_title=window.title if window is not None else "",
            capture_metadata=metadata,
        )

    return CaptureFrame(
        backend,
        width,
        height,
        source,
        status=CaptureStatus.CAPTURE_ACTIVE,
        debug_capture_enabled=privacy_policy.debug_capture_opt_in,
        window_handle=int(selected_handle),
        window_title=window.title if window is not None else "",
        capture_metadata=metadata,
    )


def _capture_window_image(window: WindowDescriptor | None) -> CapturedImage | None:
    if window is None or window.width <= 0 or window.height <= 0:
        return None
    try:
        from PIL import ImageGrab
    except Exception:
        return None

    bbox = window.capture_rect()
    try:
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception:
        return None
    if image is None:
        return None

    capture_dir = Path(tempfile.gettempdir()) / "ocring-live-captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_id = f"window-{window.handle}-{time.time_ns()}"
    output_path = capture_dir / f"{capture_id}.png"
    temp_path = capture_dir / f"{capture_id}.tmp"
    _save_capture_image_atomic(image, temp_path=temp_path, output_path=output_path)
    width, height = image.size
    return CapturedImage(output_path=output_path, width=int(width), height=int(height), capture_rect=bbox)


def _save_capture_image_atomic(image, *, temp_path: Path, output_path: Path) -> None:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    with temp_path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.rename(temp_path, output_path)


def validate_capture_surface(window: WindowDescriptor | None) -> CaptureSurfaceCheck:
    if window is None:
        return CaptureSurfaceCheck(False, "TARGET_WINDOW_NOT_FOUND")
    if not window.is_visible:
        return CaptureSurfaceCheck(False, "TARGET_WINDOW_NOT_VISIBLE")
    if window.is_iconic:
        return CaptureSurfaceCheck(False, "TARGET_WINDOW_MINIMIZED")
    capture_rect = window.capture_rect()
    return validate_captured_dimensions(
        width=max(0, capture_rect[2] - capture_rect[0]),
        height=max(0, capture_rect[3] - capture_rect[1]),
    )


def validate_captured_dimensions(width: int, height: int) -> CaptureSurfaceCheck:
    normalized_width = max(0, int(width))
    normalized_height = max(0, int(height))
    if normalized_width < _MIN_GAMEPLAY_WIDTH:
        return CaptureSurfaceCheck(False, "CAPTURE_WIDTH_TOO_SMALL")
    if normalized_height < _MIN_GAMEPLAY_HEIGHT:
        return CaptureSurfaceCheck(False, "CAPTURE_HEIGHT_TOO_SMALL")
    if normalized_height <= 0:
        return CaptureSurfaceCheck(False, "CAPTURE_HEIGHT_INVALID")
    aspect_ratio = normalized_width / float(normalized_height)
    if aspect_ratio < _MIN_GAMEPLAY_ASPECT or aspect_ratio > _MAX_GAMEPLAY_ASPECT:
        return CaptureSurfaceCheck(False, "CAPTURE_ASPECT_RATIO_INVALID")
    return CaptureSurfaceCheck(True, "")


def _window_text(hwnd: int) -> str:
    length = _USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    _USER32.GetWindowTextW(hwnd, title_buffer, length + 1)
    return title_buffer.value.strip()


def _read_dwm_extended_frame_bounds(hwnd: int) -> _RECT | None:
    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        return None
    rect = _RECT()
    try:
        result = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(_DWM_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
    except Exception:
        return None
    if int(result) != 0:
        return None
    return rect
