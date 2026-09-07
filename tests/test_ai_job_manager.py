from __future__ import annotations

import pytest

from ocring.ocr.ai_job_manager import AIJob, AIJobManager, JobPriority, PrivacyLevel


def test_ai_job_manager_orders_by_priority_and_tracks_queue_position() -> None:
    manager = AIJobManager(budget_per_session=10.0, budget_per_day=20.0, max_requests_per_sec=2)
    low = AIJob("b", JobPriority.LOW, 5.0, 0, 1.0, PrivacyLevel.LOCAL_ONLY, (100, 40), "tok-low")
    high = AIJob("a", JobPriority.HIGH, 5.0, 0, 1.0, PrivacyLevel.API, (100, 40), "tok-high")

    manager.enqueue(low)
    manager.enqueue(high)
    snapshot = manager.queue_snapshot()

    assert snapshot[0].job_id == "a"
    assert snapshot[0].queue_position == 1
    assert snapshot[1].queue_position == 2


def test_ai_job_manager_enforces_budget_controls() -> None:
    manager = AIJobManager(budget_per_session=1.5, budget_per_day=10.0, max_requests_per_sec=1)
    manager.enqueue(AIJob("a", JobPriority.MEDIUM, 5.0, 0, 1.0, PrivacyLevel.LOCAL_ONLY, (50, 50), "tok"))

    with pytest.raises(ValueError):
        manager.enqueue(AIJob("b", JobPriority.MEDIUM, 5.0, 0, 1.0, PrivacyLevel.LOCAL_ONLY, (50, 50), "tok2"))

