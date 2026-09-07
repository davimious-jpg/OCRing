from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PrivacyLevel(str, Enum):
    PUBLIC = "PUBLIC"
    LOCAL_ONLY = "LOCAL_ONLY"
    API = "API"


@dataclass
class AIJob:
    job_id: str
    priority: JobPriority
    timeout: float
    retry_count: int
    cost_estimate: float
    privacy_level: PrivacyLevel
    crop_size: tuple[int, int]
    cancellation_token: str
    payload: dict[str, Any] = field(default_factory=dict)
    queue_position: int = 0


class AIJobManager:
    def __init__(
        self,
        *,
        budget_per_session: float,
        budget_per_day: float,
        max_requests_per_sec: int,
    ) -> None:
        self.budget_per_session = budget_per_session
        self.budget_per_day = budget_per_day
        self.max_requests_per_sec = max_requests_per_sec
        self._jobs: list[AIJob] = []
        self._session_spend = 0.0
        self._day_spend = 0.0

    def enqueue(self, job: AIJob) -> AIJob:
        if self._session_spend + job.cost_estimate > self.budget_per_session:
            raise ValueError("Session AI budget exceeded.")
        if self._day_spend + job.cost_estimate > self.budget_per_day:
            raise ValueError("Daily AI budget exceeded.")
        self._jobs.append(job)
        self._sort_jobs()
        self._session_spend += job.cost_estimate
        self._day_spend += job.cost_estimate
        return job

    def next_job(self) -> AIJob | None:
        if not self._jobs:
            return None
        return self._jobs.pop(0)

    def queue_snapshot(self) -> tuple[AIJob, ...]:
        return tuple(self._jobs)

    def spending(self) -> dict[str, float]:
        return {
            "budget_per_session": self.budget_per_session,
            "budget_per_day": self.budget_per_day,
            "session_spend": round(self._session_spend, 3),
            "day_spend": round(self._day_spend, 3),
        }

    def _sort_jobs(self) -> None:
        rank = {
            JobPriority.HIGH: 0,
            JobPriority.MEDIUM: 1,
            JobPriority.LOW: 2,
        }
        self._jobs.sort(key=lambda job: (rank[job.priority], job.job_id))
        for index, job in enumerate(self._jobs, start=1):
            job.queue_position = index

