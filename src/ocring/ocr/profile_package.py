from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .profile import DEFAULT_PROFILES_ROOT, load_profile, save_profile
from .profile_validator import validate_profile


@dataclass(frozen=True)
class ProfilePackageManifest:
    profile_id: str
    profile_name: str
    version: str
    author: str
    export_date: str
    ocring_version: str


class ProfilePackage:
    def __init__(self, *, profiles_root: Path = DEFAULT_PROFILES_ROOT, ocring_version: str = "0.1") -> None:
        self.profiles_root = profiles_root
        self.ocring_version = ocring_version

    def export_profile(
        self,
        profile_id: str,
        output_path: str,
        *,
        author: str = "unknown",
        readme_text: str | None = None,
    ) -> Path:
        profile = load_profile(profile_id, profiles_root=self.profiles_root)
        issues = validate_profile(profile)
        errors = [issue for issue in issues if issue.severity == "ERROR"]
        if errors:
            messages = "; ".join(issue.message for issue in errors)
            raise ValueError(f"profile validation failed before export: {messages}")

        output = Path(output_path)
        if output.suffix.lower() != ".ocring-profile":
            output = output.with_suffix(".ocring-profile")
        output.parent.mkdir(parents=True, exist_ok=True)

        manifest = ProfilePackageManifest(
            profile_id=profile.profile_id,
            profile_name=profile.profile_name,
            version=profile.version,
            author=author,
            export_date=datetime.now(timezone.utc).isoformat(),
            ocring_version=self.ocring_version,
        )
        profile_dir = self.profiles_root / profile_id
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest.__dict__, indent=2, sort_keys=True))
            archive.writestr("profile.json", json.dumps(profile.as_dict(), indent=2, sort_keys=True))
            if readme_text:
                archive.writestr("readme.txt", readme_text)
            reference_dir = profile_dir / "reference_data"
            if reference_dir.exists():
                for file_path in sorted(reference_dir.rglob("*")):
                    if file_path.is_file():
                        archive.write(file_path, arcname=str(Path("reference_data") / file_path.relative_to(reference_dir)))
        return output

    def import_profile(self, package_path: str, *, overwrite: bool = False) -> str:
        package = Path(package_path)
        with zipfile.ZipFile(package, "r") as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names or "profile.json" not in names:
                raise ValueError("invalid profile package: manifest.json and profile.json are required")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            payload = json.loads(archive.read("profile.json").decode("utf-8"))

            profile_id = str(payload.get("profile_id") or manifest.get("profile_id") or "").strip()
            if not profile_id:
                raise ValueError("invalid profile package: profile_id is required")
            target_profile_id = profile_id
            target_dir = self.profiles_root / target_profile_id
            if target_dir.exists():
                if overwrite:
                    shutil.rmtree(target_dir)
                else:
                    target_profile_id = self._next_available_profile_id(profile_id)
                    target_dir = self.profiles_root / target_profile_id
            target_dir.mkdir(parents=True, exist_ok=True)

            payload["profile_id"] = target_profile_id
            profile_json_path = target_dir / "profile.json"
            profile_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            self._extract_optional_content(archive, target_dir)

        profile = load_profile(target_profile_id, profiles_root=self.profiles_root)
        save_profile(profile, profiles_root=self.profiles_root)
        return target_profile_id

    def _extract_optional_content(self, archive: zipfile.ZipFile, target_dir: Path) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for member in archive.namelist():
                if member in {"manifest.json", "profile.json"}:
                    continue
                if not member.startswith("reference_data/") and member != "readme.txt":
                    continue
                archive.extract(member, path=temp_root)
            for item in temp_root.rglob("*"):
                if item.is_dir():
                    continue
                relative = item.relative_to(temp_root)
                destination = target_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)

    def _next_available_profile_id(self, base_profile_id: str) -> str:
        suffix = 1
        while True:
            candidate = f"{base_profile_id}-imported-{suffix}"
            if not (self.profiles_root / candidate).exists():
                return candidate
            suffix += 1
