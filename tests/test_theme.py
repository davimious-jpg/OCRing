from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from ocring.ui.theme import ACCENT, ACCENT_STRONG, _is_ttk_monitor_window, apply_modern_theme, hide_ttk_monitor_windows


def test_theme_identifies_ttk_monitor_helper_window() -> None:
    assert _is_ttk_monitor_window("TtkMonitorWindow", "")
    assert _is_ttk_monitor_window("", "TtkMonitorClass")
    assert not _is_ttk_monitor_window("OCRing", "TkTopLevel")


def test_hide_ttk_monitor_windows_returns_count() -> None:
    assert isinstance(hide_ttk_monitor_windows(), int)


def test_disabled_accent_button_does_not_look_enabled_cyan() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable for theme check: {error}")
    root.withdraw()
    apply_modern_theme(root)
    style = ttk.Style(root)

    disabled_backgrounds = [value for states, value in style.map("Accent.TButton", "background") if "disabled" in states]

    assert disabled_backgrounds
    assert disabled_backgrounds[0] not in {ACCENT, ACCENT_STRONG}
    root.destroy()
