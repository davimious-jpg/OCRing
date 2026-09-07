from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from PIL import ImageGrab

from ocring.ocr.capture_backend import get_window_descriptor, list_available_windows
from ocring.ocr.settings import ensure_output_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone live capture verification for OCRing.")
    parser.add_argument("--handle", type=int, help="Optional explicit window handle to capture.")
    parser.add_argument("--title-contains", default="Defiance", help="Window title substring to match.")
    return parser


def select_window(*, handle: int | None, title_contains: str):
    if handle is not None:
        return get_window_descriptor(handle)
    candidates = list_available_windows()
    lowered = title_contains.lower()
    for window in candidates:
        if lowered in window.title.lower():
            return window
    return candidates[0] if candidates else None


def main() -> int:
    args = build_parser().parse_args()
    workspace = ensure_output_workspace()
    output_path = workspace.root / "capture_test.png"
    window = select_window(handle=args.handle, title_contains=args.title_contains)

    if window is None:
        print("Window found: NONE")
        print("Capture success: false")
        print("Frame dimensions: 0x0")
        print(f"Save path: {output_path}")
        print("Traceback:")
        print("No visible windows were available for capture.")
        return 1

    print(f"Window found: {window.title} [{window.handle}]")
    try:
        image = ImageGrab.grab(
            bbox=(window.left, window.top, window.right, window.bottom),
            all_screens=True,
        )
        image.save(output_path)
        width, height = image.size
        print("Capture success: true")
        print(f"Frame dimensions: {width}x{height}")
        print(f"Save path: {output_path}")
        print(json.dumps({"created": output_path.exists(), "bytes": output_path.stat().st_size}, indent=2))
        return 0
    except Exception:
        print("Capture success: false")
        print("Frame dimensions: 0x0")
        print(f"Save path: {output_path}")
        print("Traceback:")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
