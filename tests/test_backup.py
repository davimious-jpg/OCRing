from __future__ import annotations

import json

from ocring.ocr.backup import BackupPackage


def test_backup_export_and_import_use_merge_diff_logic(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "profiles" / "defiance").mkdir(parents=True)
    (source / "profiles" / "defiance" / "profile.json").write_text('{"profile_id":"defiance"}', encoding="utf-8")
    (source / "inventory.db").write_bytes(b"inventory")
    (source / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")

    package_path = tmp_path / "backup.zip"
    backup = BackupPackage()
    backup.export(source, package_path)

    target = tmp_path / "target"
    target.mkdir()
    (target / "settings.json").write_text('{"theme":"dark","scale":1}', encoding="utf-8")

    result = backup.import_package(package_path, target)

    settings = json.loads((target / "settings.json").read_text(encoding="utf-8"))
    assert "settings.json" in result.merged_files
    assert settings["theme"] == "light"
    assert settings["scale"] == 1
    assert (target / "profiles" / "defiance" / "profile.json").exists()

