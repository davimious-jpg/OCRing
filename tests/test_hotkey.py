from __future__ import annotations

from pathlib import Path

from ocring.ocr.event_bus import EventBus, UIEvent
from ocring.ui.hotkey import HotkeyManager, TkHotkeyBackend, choose_hotkey_backend


class _FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.registered: list[str] = []
        self.callback = None

    def register(self, hotkey: str, callback) -> object:
        self.registered.append(hotkey)
        self.callback = callback

        def unregister() -> None:
            self.callback = None

        return unregister


def test_hotkey_registration_and_toggle_behavior(tmp_path: Path) -> None:
    bus = EventBus()
    backend = _FakeBackend()
    manager = HotkeyManager(
        event_bus=bus,
        backend=backend,
        settings_path=tmp_path / "settings.json",
        hotkey="Alt+F8",
    )
    received: list[UIEvent] = []
    bus.subscribe(UIEvent.SCAN_START_REQUESTED, lambda message: received.append(message.event_type))
    bus.subscribe(UIEvent.SCAN_STOP_REQUESTED, lambda message: received.append(message.event_type))

    manager.register()
    assert backend.registered == ["Alt+F8"]

    manager.toggle_scan()
    manager.toggle_scan()

    assert received == [UIEvent.SCAN_START_REQUESTED, UIEvent.SCAN_STOP_REQUESTED]
    manager.close()


def test_hotkey_rebind_publishes_event(tmp_path: Path) -> None:
    bus = EventBus()
    backend = _FakeBackend()
    manager = HotkeyManager(
        event_bus=bus,
        backend=backend,
        settings_path=tmp_path / "settings.json",
        hotkey="Alt+F8",
    )
    rebound: list[str] = []
    bus.subscribe(UIEvent.HOTKEY_REBOUND, lambda message: rebound.append(str(message.payload["scan_hotkey"])))

    manager.register()
    updated = manager.rebind("Ctrl+F9")

    assert updated == "Ctrl+F9"
    assert backend.registered == ["Alt+F8", "Ctrl+F9"]
    assert rebound == ["Ctrl+F9"]
    manager.close()


def test_hotkey_manager_prefers_global_backend_when_available(tmp_path: Path) -> None:
    bus = EventBus()
    backend = _FakeBackend()
    manager = HotkeyManager(
        event_bus=bus,
        backend=backend,
        settings_path=tmp_path / "settings.json",
        hotkey="Alt+F8",
    )

    backend_name = manager.register()

    assert backend_name == "fake"
    assert manager.is_global_backend is True
    assert backend.registered == ["Alt+F8"]
    manager.close()


def test_choose_hotkey_backend_falls_back_to_tk_when_keyboard_library_is_unavailable(monkeypatch) -> None:
    import builtins
    import tkinter as tk

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "keyboard":
            raise ImportError("keyboard missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    root = tk.Tcl()

    backend, warning = choose_hotkey_backend(root)

    assert isinstance(backend, TkHotkeyBackend)
    assert warning == "Global hotkey library unavailable; using Tk fallback."
