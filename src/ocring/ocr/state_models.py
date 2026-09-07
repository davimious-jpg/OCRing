from __future__ import annotations

from enum import Enum


class FieldStatus(str, Enum):
    OBSERVED = "OBSERVED"
    DEFAULTED = "DEFAULTED"
    UNKNOWN = "UNKNOWN"
    NOT_VISIBLE = "NOT_VISIBLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ABSENT = "ABSENT"

