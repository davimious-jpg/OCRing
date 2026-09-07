from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ocring.ocr.generic_profile import create_generic_profile, save_generic_profile
from ocring.ocr.profile import create_default_template, load_profile, save_profile
from ocring.ocr.profile_package import ProfilePackage


def test_profile_export_import_round_trip(tmp_path: Path) -> None:
    profiles_root = tmp_path / "profiles"
    profile = create_default_template()
    profile.profile_name = "Packaged Profile"
    save_profile(profile, profiles_root=profiles_root)
    package_manager = ProfilePackage(profiles_root=profiles_root)
    package_path = tmp_path / "exports" / "packaged.ocring-profile"

    exported = package_manager.export_profile(profile.profile_id, str(package_path))

    imported_root = tmp_path / "imported"
    imported_manager = ProfilePackage(profiles_root=imported_root)
    imported_profile_id = imported_manager.import_profile(str(exported))
    imported_profile = load_profile(imported_profile_id, profiles_root=imported_root)

    assert exported.exists()
    assert imported_profile.profile_name == "Packaged Profile"
    assert imported_profile.profile_id == profile.profile_id


def test_profile_package_manifest_validation_fails_when_required_files_missing(tmp_path: Path) -> None:
    package_path = tmp_path / "broken.ocring-profile"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("profile.json", json.dumps({"profile_id": "broken"}))

    manager = ProfilePackage(profiles_root=tmp_path / "profiles")

    try:
        manager.import_profile(str(package_path))
    except ValueError as error:
        assert "manifest.json and profile.json are required" in str(error)
    else:
        raise AssertionError("expected package import to fail without manifest.json")


def test_profile_package_conflict_detection_renames_when_not_overwriting(tmp_path: Path) -> None:
    profiles_root = tmp_path / "profiles"
    profile = create_default_template()
    profile.profile_name = "Conflict Source"
    save_profile(profile, profiles_root=profiles_root)
    manager = ProfilePackage(profiles_root=profiles_root)
    package_path = manager.export_profile(profile.profile_id, str(tmp_path / "conflict.ocring-profile"))

    imported_profile_id = manager.import_profile(str(package_path), overwrite=False)

    assert imported_profile_id != profile.profile_id
    assert imported_profile_id.startswith(f"{profile.profile_id}-imported-")
    assert (profiles_root / imported_profile_id / "profile.json").exists()


def test_profile_package_import_supports_generic_profiles(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    generic = create_generic_profile(
        "Shared Generic",
        (5, 10, 300, 450),
        [{"field_name": "score", "field_type": "number", "field_source": "row 2"}],
    )
    save_generic_profile(generic, profiles_root=source_root)
    manager = ProfilePackage(profiles_root=source_root)
    package_path = manager.export_profile(generic.profile_id, str(tmp_path / "generic.ocring-profile"))

    destination_root = tmp_path / "destination"
    imported_manager = ProfilePackage(profiles_root=destination_root)
    imported_profile_id = imported_manager.import_profile(str(package_path))
    imported_profile = load_profile(imported_profile_id, profiles_root=destination_root)

    assert getattr(imported_profile, "profile_kind", "") == "generic"
    assert imported_profile.profile_name == "Shared Generic"
