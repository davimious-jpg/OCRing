from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1


@dataclass(frozen=True)
class RecordIdentity:
    canonical_item_id: str
    instance_fingerprint: str
    scan_observation_ids: tuple[str, ...]


def build_record_identity(
    *,
    canonical_item_id: str,
    observation_ids: tuple[str, ...],
    name: str = "",
    rarity: str = "",
    synergy: str = "",
    item_type: str = "",
    mods: tuple[str, ...] = (),
    stats: tuple[str, ...] = (),
) -> RecordIdentity:
    fingerprint_parts = (
        canonical_item_id.strip().lower(),
        name.strip().lower(),
        rarity.strip().lower(),
        synergy.strip().lower(),
        item_type.strip().lower(),
        "|".join(item.strip().lower() for item in mods),
        "|".join(item.strip().lower() for item in stats),
    )
    fingerprint = sha1("::".join(fingerprint_parts).encode("utf-8")).hexdigest()
    return RecordIdentity(canonical_item_id, fingerprint, tuple(observation_ids))

