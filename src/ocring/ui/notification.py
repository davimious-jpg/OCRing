from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class NotificationRecord:
    severity: NotificationSeverity
    message: str
    created_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))


class NotificationCenter:
    def __init__(self) -> None:
        self._log: list[NotificationRecord] = []

    def notify(self, severity: NotificationSeverity, message: str) -> NotificationRecord:
        record = NotificationRecord(severity=severity, message=message)
        self._log.append(record)
        return record

    def history(self) -> tuple[NotificationRecord, ...]:
        return tuple(self._log)

