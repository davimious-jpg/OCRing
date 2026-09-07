from __future__ import annotations

import json
import re
import tkinter as tk
from pathlib import Path
from typing import Callable, Protocol

from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ocr.settings import DEFAULT_SETTINGS_PATH


DEFAULT_SCAN_HOTKEY = "Alt+F8"


class HotkeyBackend(Protocol):
    name: str

    def register(self, hotkey: str, callback: Callable[[], None]) -> Callable[[], None]:
        ...


def load_hotkey_mapping(*, settings_path: Path = DEFAULT_SETTINGS_PATH) -> str:
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SCAN_HOTKEY
    return normalize_hotkey(str(payload.get("scan_hotkey") or DEFAULT_SCAN_HOTKEY))


def normalize_hotkey(hotkey: str) -> str:
    cleaned = re.sub(r"\s+", "", str(hotkey or DEFAULT_SCAN_HOTKEY))
    if not cleaned:
        return DEFAULT_SCAN_HOTKEY
    parts = [part for part in re.split(r"[+]", cleaned) if part]
    normalized: list[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in {"ctrl", "control"}:
            normalized.append("Ctrl")
        elif lowered == "alt":
            normalized.append("Alt")
        elif lowered == "shift":
            normalized.append("Shift")
        elif lowered.startswith("f") and lowered[1:].isdigit():
            normalized.append(lowered.upper())
        else:
            normalized.append(part.upper() if len(part) == 1 else part.title())
    return "+".join(normalized) if normalized else DEFAULT_SCAN_HOTKEY


def event_to_hotkey(event: object) -> str:
    state = int(getattr(event, "state", 0))
    keysym = str(getattr(event, "keysym", "") or getattr(event, "char", "")).upper()
    parts: list[str] = []
    if state & 0x0004:
        parts.append("Ctrl")
    if state & 0x0001 or state & 0x0008:
        parts.append("Shift")
    if state & 0x0008 or state & 0x20000:
        if "Shift" not in parts:
            parts.append("Alt")
    if not keysym:
        return DEFAULT_SCAN_HOTKEY
    parts.append(keysym)
    return normalize_hotkey("+".join(parts))


def tk_sequence_for_hotkey(hotkey: str) -> str:
    parts = normalize_hotkey(hotkey).split("+")
    if not parts:
        return "<Alt-F8>"
    key = parts[-1]
    modifiers = "-".join(part for part in parts[:-1] if part in {"Ctrl", "Alt", "Shift"})
    if modifiers:
        return f"<{modifiers}-{key}>"
    return f"<{key}>"


class KeyboardLibraryBackend:
    name = "keyboard"

    def __init__(self) -> None:
        import keyboard  # type: ignore

        self._keyboard = keyboard

    def register(self, hotkey: str, callback: Callable[[], None]) -> Callable[[], None]:
        handle = self._keyboard.add_hotkey(normalize_hotkey(hotkey).lower(), callback)

        def unregister() -> None:
            self._keyboard.remove_hotkey(handle)

        return unregister


class TkHotkeyBackend:
    name = "tkinter"

    def __init__(self, root: tk.Misc) -> None:
        self.root = root

    def register(self, hotkey: str, callback: Callable[[], None]) -> Callable[[], None]:
        sequence = tk_sequence_for_hotkey(hotkey)

        def handler(_event: object) -> str:
            callback()
            return "break"

        self.root.bind_all(sequence, handler)

        def unregister() -> None:
            if hasattr(self.root, "unbind_all"):
                self.root.unbind_all(sequence)

        return unregister


def choose_hotkey_backend(root: tk.Misc | None = None) -> tuple[HotkeyBackend, str | None]:
    try:
        return KeyboardLibraryBackend(), None
    except Exception:
        if root is not None:
            return TkHotkeyBackend(root), "Global hotkey library unavailable; using Tk fallback."
        raise


class HotkeyManager:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        root: tk.Misc | None = None,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
        backend: HotkeyBackend | None = None,
        hotkey: str | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.root = root
        self.settings_path = settings_path
        self.hotkey = normalize_hotkey(hotkey or load_hotkey_mapping(settings_path=settings_path))
        self.backend = backend
        self.backend_warning: str | None = None
        self.is_global_backend = False
        self._registered_backend: HotkeyBackend | None = None
        self._unregister: Callable[[], None] | None = None
        self.scan_state = "READY"
        self._unsubscribe_started = event_bus.subscribe(UIEvent.SCAN_STARTED, self._on_scan_started)
        self._unsubscribe_stop = event_bus.subscribe(UIEvent.SCAN_STOP_REQUESTED, self._on_scan_stopped)

    @property
    def backend_scope_label(self) -> str:
        return "global" if self.is_global_backend else "window-scoped fallback"

    @property
    def backend_status_label(self) -> str:
        backend_name = getattr(self._registered_backend, "name", None) or getattr(self.backend, "name", None) or "unbound"
        return f"{self.hotkey} via {backend_name} ({self.backend_scope_label})"

    def register(self) -> str:
        self.unregister()
        backend = self.backend
        if backend is None:
            backend, self.backend_warning = choose_hotkey_backend(self.root)
        else:
            self.backend_warning = None
        self._registered_backend = backend
        self.is_global_backend = backend.name != "tkinter"
        self._unregister = backend.register(self.hotkey, self.toggle_scan)
        return backend.name

    def unregister(self) -> None:
        if self._unregister is not None:
            self._unregister()
            self._unregister = None

    def close(self) -> None:
        self.unregister()
        self._unsubscribe_started()
        self._unsubscribe_stop()

    def toggle_scan(self) -> None:
        if self.scan_state == "LIVE":
            self.scan_state = "READY"
            self.event_bus.publish(UIEvent.SCAN_STOP_REQUESTED, {"hotkey": self.hotkey})
            return
        self.scan_state = "LIVE"
        self.event_bus.publish(UIEvent.SCAN_START_REQUESTED, {"hotkey": self.hotkey})

    def rebind(self, hotkey: str) -> str:
        self.hotkey = normalize_hotkey(hotkey)
        self.register()
        self.event_bus.publish(UIEvent.HOTKEY_REBOUND, {"scan_hotkey": self.hotkey})
        return self.hotkey

    def _on_scan_started(self, _message: object) -> None:
        self.scan_state = "LIVE"

    def _on_scan_stopped(self, _message: object) -> None:
        self.scan_state = "READY"
