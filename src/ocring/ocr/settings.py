from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_SETTINGS_PATH = Path("E:/Ocring/settings.json")
DEFAULT_OUTPUT_ROOT = Path("E:/Ocring/output")
DEFAULT_WINDOW_GEOMETRY = "1024x768"


@dataclass(frozen=True)
class OutputWorkspace:
    root: Path
    export_dir: Path
    sessions_dir: Path
    evidence_dir: Path
    checkpoints_dir: Path
    inventory_db: Path


@dataclass(frozen=True)
class RecognitionSettings:
    recognition_mode: str = "Balanced"
    api_escalation: str = "Automatically below confidence threshold"
    privacy: str = "Send cropped regions only"
    review_mode: str = "Strict Manual Review"
    output_root: str = str(DEFAULT_OUTPUT_ROOT)
    window_geometry: str = DEFAULT_WINDOW_GEOMETRY

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def load_settings_payload(*, path: Path = DEFAULT_SETTINGS_PATH) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def load_settings(*, path: Path = DEFAULT_SETTINGS_PATH) -> RecognitionSettings:
    payload = load_settings_payload(path=path)
    return RecognitionSettings(
        recognition_mode=str(payload.get("recognition_mode") or "Balanced"),
        api_escalation=str(payload.get("api_escalation") or "Automatically below confidence threshold"),
        privacy=str(payload.get("privacy") or "Send cropped regions only"),
        review_mode=str(payload.get("review_mode") or "Strict Manual Review"),
        output_root=str(payload.get("output_root") or DEFAULT_OUTPUT_ROOT),
        window_geometry=str(payload.get("window_geometry") or DEFAULT_WINDOW_GEOMETRY),
    )


def save_settings(settings: RecognitionSettings, *, path: Path = DEFAULT_SETTINGS_PATH) -> Path:
    payload = load_settings_payload(path=path)
    payload.update(settings.as_dict())
    return save_settings_payload(payload, path=path)


def save_settings_payload(payload: dict[str, object], *, path: Path = DEFAULT_SETTINGS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def resolve_output_root(output_root: str | Path | None = None, *, path: Path = DEFAULT_SETTINGS_PATH) -> Path:
    if output_root is None:
        output_root = load_settings(path=path).output_root
    return Path(output_root)


def ensure_output_workspace(
    output_root: str | Path | None = None,
    *,
    path: Path = DEFAULT_SETTINGS_PATH,
) -> OutputWorkspace:
    root = resolve_output_root(output_root, path=path)
    export_dir = root / "export"
    sessions_dir = root / "sessions"
    evidence_dir = root / "evidence"
    checkpoints_dir = sessions_dir / "checkpoints"

    for directory in (root, export_dir, sessions_dir, evidence_dir, checkpoints_dir):
        directory.mkdir(parents=True, exist_ok=True)

    return OutputWorkspace(
        root=root,
        export_dir=export_dir,
        sessions_dir=sessions_dir,
        evidence_dir=evidence_dir,
        checkpoints_dir=checkpoints_dir,
        inventory_db=sessions_dir / "review_inventory.db",
    )


def open_in_file_manager(target: str | Path) -> Path:
    path = Path(target)
    if hasattr(os, "startfile"):
        if path.is_file():
            os.startfile(path.parent)
        else:
            os.startfile(path)
        return path
    if path.is_file():
        subprocess.Popen(["explorer", str(path.parent)])
    else:
        subprocess.Popen(["explorer", str(path)])
    return path
