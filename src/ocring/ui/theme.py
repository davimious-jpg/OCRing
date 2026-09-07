from __future__ import annotations

import os
from pathlib import Path
from tkinter import ttk

APP_BG = "#09131d"
SURFACE_BG = "#102131"
SURFACE_ALT_BG = "#15293a"
ACCENT = "#5de4ff"
ACCENT_STRONG = "#22b8cf"
TEXT = "#eef7ff"
TEXT_MUTED = "#9fb7c9"
BORDER = "#23465d"
SUCCESS = "#22c55e"
WARNING = "#fbbf24"
DANGER = "#ef4444"

BODY_FONT = ("Segoe UI", 11)
TITLE_FONT = ("Segoe UI Semibold", 12)
HEADER_FONT = ("Segoe UI Semibold", 18)
STATUS_FONT = ("Segoe UI Semibold", 16)


def _is_ttk_monitor_window(title: str, class_name: str) -> bool:
    return title == "TtkMonitorWindow" or class_name == "TtkMonitorClass"


def hide_ttk_monitor_windows() -> int:
    """Hide Tk's internal monitor helper if Windows ever maps it visibly."""
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return 0

    user32 = ctypes.windll.user32
    current_pid = os.getpid()
    hidden_count = 0

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _window_text(hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _class_name(hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value

    def _enum(hwnd: int, _lparam: int) -> bool:
        nonlocal hidden_count
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != current_pid:
            return True
        if _is_ttk_monitor_window(_window_text(hwnd), _class_name(hwnd)):
            user32.ShowWindow(hwnd, 0)
            hidden_count += 1
        return True

    try:
        user32.EnumWindows(EnumWindowsProc(_enum), 0)
    except Exception:
        return hidden_count
    return hidden_count


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_logo_path() -> Path | None:
    candidates = (
        project_root() / "ocring_logo.png",
        project_root() / "ocring logo.png",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def apply_window_icon(root: object) -> object | None:
    if not hasattr(root, "iconphoto"):
        return None
    logo_path = resolve_logo_path()
    if logo_path is None:
        return None
    try:
        import tkinter as tk

        image = tk.PhotoImage(file=str(logo_path))
        root.iconphoto(True, image)
        setattr(root, "_ocring_icon", image)
        return image
    except Exception:
        return None


def load_logo_image(master: object, *, base_size: tuple[int, int] = (40, 40)) -> object | None:
    logo_path = resolve_logo_path()
    if logo_path is None:
        return None
    try:
        from PIL import Image, ImageTk

        scale = 1.0
        tk_interp = getattr(master, "tk", None)
        if tk_interp is not None:
            try:
                scale = float(tk_interp.call("tk", "scaling"))
            except Exception:
                scale = 1.0
        width = max(24, int(base_size[0] * max(1.0, min(1.5, scale))))
        height = max(24, int(base_size[1] * max(1.0, min(1.5, scale))))
        image = Image.open(logo_path).convert("RGBA")
        image = image.resize((width, height))
        return ImageTk.PhotoImage(image, master=master)
    except Exception:
        return None


def apply_modern_theme(root: object) -> None:
    if hasattr(root, "configure"):
        try:
            root.configure(bg=APP_BG)
        except Exception:
            pass
    try:
        style = ttk.Style(root)
    except Exception:
        return
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=APP_BG, foreground=TEXT, font=BODY_FONT)
    style.configure("TFrame", background=APP_BG)
    style.configure("Surface.TFrame", background=SURFACE_BG)
    style.configure("AltSurface.TFrame", background=SURFACE_ALT_BG)
    style.configure("TLabel", background=APP_BG, foreground=TEXT, font=BODY_FONT)
    style.configure("Muted.TLabel", background=APP_BG, foreground=TEXT_MUTED, font=BODY_FONT)
    style.configure("Header.TLabel", background=APP_BG, foreground=TEXT, font=HEADER_FONT)
    style.configure("Section.TLabel", background=APP_BG, foreground=ACCENT, font=TITLE_FONT)
    style.configure("Card.TLabel", background=SURFACE_BG, foreground=TEXT, font=BODY_FONT)
    style.configure(
        "TButton",
        background=SURFACE_ALT_BG,
        foreground=TEXT,
        bordercolor=BORDER,
        focusthickness=1,
        focuscolor=ACCENT_STRONG,
        padding=(12, 8),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("disabled", "#1f2937"), ("active", ACCENT_STRONG), ("pressed", ACCENT)],
        foreground=[("disabled", TEXT_MUTED), ("active", APP_BG), ("pressed", APP_BG)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT_STRONG,
        foreground=APP_BG,
        bordercolor=ACCENT,
        padding=(14, 9),
        relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", "#263241"), ("active", ACCENT), ("pressed", ACCENT_STRONG)],
        foreground=[("disabled", TEXT_MUTED), ("active", APP_BG), ("pressed", APP_BG)],
    )
    style.configure(
        "TEntry",
        fieldbackground=SURFACE_BG,
        foreground=TEXT,
        insertcolor=TEXT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_BG,
        foreground=TEXT,
        arrowcolor=ACCENT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE_BG)])
    style.configure("TNotebook", background=APP_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=SURFACE_ALT_BG, foreground=TEXT_MUTED, padding=(14, 8))
    style.map("TNotebook.Tab", background=[("selected", SURFACE_BG)], foreground=[("selected", ACCENT)])
    style.configure("TLabelframe", background=APP_BG, bordercolor=BORDER, relief="solid")
    style.configure("TLabelframe.Label", background=APP_BG, foreground=ACCENT, font=TITLE_FONT)
    style.configure("TCheckbutton", background=APP_BG, foreground=TEXT, font=BODY_FONT)
