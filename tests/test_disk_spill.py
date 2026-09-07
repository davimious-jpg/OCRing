from __future__ import annotations

from ocring.ocr.disk_spill import DiskSpillCache, RAM_SPILL_THRESHOLD_BYTES


def test_disk_spill_preserves_only_worthy_unresolved_evidence(tmp_path) -> None:
    cache = DiskSpillCache(tmp_path)
    result = cache.spill_if_needed(
        [
            {"id": "a", "unresolved": True},
            {"id": "b", "anchor": True},
            {"id": "c", "resolved": True},
        ],
        ram_bytes=RAM_SPILL_THRESHOLD_BYTES,
    )

    assert result.spilled_count == 2
    assert all(path.exists() for path in result.spilled_paths)

