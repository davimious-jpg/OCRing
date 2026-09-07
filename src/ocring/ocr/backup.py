from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import zipfile


@dataclass(frozen=True)
class ImportResult:
    merged_files: tuple[str, ...]
    changed_files: tuple[str, ...]


class BackupPackage:
    FILES = (
        "inventory.db",
        "corrections.db",
        "settings.json",
        "saved_searches.json",
    )

    def export(self, root: Path, output_path: Path) -> Path:
        with zipfile.ZipFile(output_path, "w") as archive:
            profiles_root = root / "profiles"
            if profiles_root.exists():
                for path in profiles_root.rglob("*"):
                    if path.is_file():
                        archive.write(path, arcname=str(path.relative_to(root)).replace("\\", "/"))
            for filename in self.FILES:
                path = root / filename
                if path.exists():
                    archive.write(path, arcname=filename)
        return output_path

    def import_package(self, package_path: Path, target_root: Path) -> ImportResult:
        merged: list[str] = []
        changed: list[str] = []
        with zipfile.ZipFile(package_path) as archive:
            for member in archive.namelist():
                destination = target_root / Path(member)
                destination.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                if destination.exists():
                    if destination.suffix == ".json":
                        merged_payload = self._merge_json(destination, data)
                        destination.write_text(json.dumps(merged_payload, indent=2, sort_keys=True), encoding="utf-8")
                        merged.append(member)
                        changed.append(member)
                    else:
                        current = destination.read_bytes()
                        if current != data:
                            destination.write_bytes(data)
                            changed.append(member)
                else:
                    destination.write_bytes(data)
                    changed.append(member)
        return ImportResult(tuple(merged), tuple(changed))

    def _merge_json(self, destination: Path, incoming_bytes: bytes) -> object:
        current = json.loads(destination.read_text(encoding="utf-8"))
        incoming = json.loads(incoming_bytes.decode("utf-8"))
        if isinstance(current, dict) and isinstance(incoming, dict):
            merged = dict(current)
            merged.update(incoming)
            return merged
        return incoming

