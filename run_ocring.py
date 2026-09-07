#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ocring.cli import main as cli_main
from ocring.ui.main_window import MainWindow


CLI_COMMANDS = {
    "review",
    "recover",
    "checkpoint",
    "search",
    "export",
    "saved-search",
    "profile-editor",
    "profile-validate",
    "generic-mode",
    "scan",
    "profile-export",
    "profile-import",
    "profile-list",
}


def should_launch_main_window(argv: list[str]) -> bool:
    if not argv:
        return True
    if any(arg in {"-h", "--help", "--input", "--fixture"} for arg in argv):
        return False
    if any(arg in CLI_COMMANDS for arg in argv):
        return False
    return True


def launch_main_window() -> int:
    window = MainWindow()
    window.run()
    return 0


def entrypoint(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if should_launch_main_window(args):
        return launch_main_window()
    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(entrypoint())
