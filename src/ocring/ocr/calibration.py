from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CALIBRATION_DB = Path("E:/Ocring/sessions/calibration.db")


@dataclass
class CalibrationBucket:
    total: int = 0
    correct: int = 0
    predicted_sum: float = 0.0

    @property
    def actual_correctness(self) -> float:
        if self.total <= 0:
            return 1.0
        return self.correct / self.total

    @property
    def predicted_confidence(self) -> float:
        if self.total <= 0:
            return 1.0
        return self.predicted_sum / self.total


class CalibrationStore:
    def __init__(
        self,
        sqlite_path: Path = DEFAULT_CALIBRATION_DB,
        *,
        min_verified_corrections: int = 50,
        adjustment_bound: float = 0.05,
        min_reliability: float = 0.70,
        max_reliability: float = 0.95,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.min_verified_corrections = min_verified_corrections
        self.adjustment_bound = adjustment_bound
        self.min_reliability = min_reliability
        self.max_reliability = max_reliability
        self._ensure_schema()

    def record_correction(
        self,
        predicted: str,
        verified: str,
        engine: str,
        confidence: float,
        *,
        field_id: str = "",
        field_type: str = "generic",
        user_corrected_at: str | None = None,
    ) -> None:
        corrected_at = user_corrected_at or datetime.now(timezone.utc).isoformat()
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO verified_outcomes (
                    field_id,
                    predicted_value,
                    verified_value,
                    engine_source,
                    field_type,
                    confidence_at_time,
                    user_corrected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    field_id,
                    predicted,
                    verified,
                    engine,
                    field_type,
                    float(confidence),
                    corrected_at,
                ),
            )
            connection.commit()
        self._maybe_adjust_reliability(engine, field_type)

    def get_reliability(self, engine: str, field_type: str) -> float:
        self._ensure_schema()
        with sqlite3.connect(self.sqlite_path) as connection:
            row = connection.execute(
                """
                SELECT new_reliability
                FROM reliability_adjustments
                WHERE engine_source = ? AND field_type = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (engine, field_type),
            ).fetchone()
        if row is None:
            return 1.0
        return float(row[0])

    def get_confident_vs_correct(self) -> dict[str, object]:
        self._ensure_schema()
        with sqlite3.connect(self.sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    engine_source,
                    field_type,
                    COUNT(*) AS total,
                    AVG(confidence_at_time) AS predicted_confidence,
                    AVG(CASE WHEN predicted_value = verified_value THEN 1.0 ELSE 0.0 END) AS actual_correctness
                FROM verified_outcomes
                GROUP BY engine_source, field_type
                ORDER BY engine_source, field_type
                """
            ).fetchall()
        report: dict[str, object] = {}
        for engine_source, field_type, total, predicted_confidence, actual_correctness in rows:
            key = f"{engine_source}:{field_type}"
            report[key] = {
                "engine_source": str(engine_source),
                "field_type": str(field_type),
                "total": int(total),
                "predicted_confidence": round(float(predicted_confidence or 0.0), 3),
                "actual_correctness": round(float(actual_correctness or 0.0), 3),
                "current_reliability": round(self.get_reliability(str(engine_source), str(field_type)), 3),
                "overconfident": float(predicted_confidence or 0.0) - float(actual_correctness or 0.0) >= 0.10,
            }
        return report

    def _ensure_schema(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_outcomes (
                    field_id TEXT NOT NULL,
                    predicted_value TEXT NOT NULL,
                    verified_value TEXT NOT NULL,
                    engine_source TEXT NOT NULL,
                    field_type TEXT NOT NULL,
                    confidence_at_time REAL NOT NULL,
                    user_corrected_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reliability_adjustments (
                    engine_source TEXT NOT NULL,
                    field_type TEXT NOT NULL,
                    previous_reliability REAL NOT NULL,
                    new_reliability REAL NOT NULL,
                    sample_size INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _maybe_adjust_reliability(self, engine: str, field_type: str) -> None:
        self._ensure_schema()
        with sqlite3.connect(self.sqlite_path) as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    AVG(confidence_at_time) AS predicted_confidence,
                    AVG(CASE WHEN predicted_value = verified_value THEN 1.0 ELSE 0.0 END) AS actual_correctness
                FROM verified_outcomes
                WHERE engine_source = ? AND field_type = ?
                """,
                (engine, field_type),
            ).fetchone()
            total = int(row[0] or 0)
            if total < self.min_verified_corrections:
                return
            predicted_confidence = float(row[1] or 0.0)
            actual_correctness = float(row[2] or 0.0)
            latest = connection.execute(
                """
                SELECT new_reliability
                FROM reliability_adjustments
                WHERE engine_source = ? AND field_type = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (engine, field_type),
            ).fetchone()
            current = float(latest[0]) if latest is not None else 1.0
            target = actual_correctness if predicted_confidence <= 0 else actual_correctness / predicted_confidence
            target = max(self.min_reliability, min(self.max_reliability, target))
            delta = max(-self.adjustment_bound, min(self.adjustment_bound, target - current))
            new_value = max(self.min_reliability, min(self.max_reliability, current + delta))
            if abs(new_value - current) < 1e-9:
                return
            connection.execute(
                """
                INSERT INTO reliability_adjustments (
                    engine_source,
                    field_type,
                    previous_reliability,
                    new_reliability,
                    sample_size,
                    applied_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    engine,
                    field_type,
                    current,
                    new_value,
                    total,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()


class ConfidenceCalibrator:
    def __init__(self, *, store: CalibrationStore | None = None) -> None:
        self._buckets: dict[str, CalibrationBucket] = {}
        self.store = store

    def record_verification(self, source_key: str, *, predicted_confidence: float, actual_correct: bool) -> None:
        bucket = self._buckets.setdefault(source_key, CalibrationBucket())
        bucket.total += 1
        bucket.correct += 1 if actual_correct else 0
        bucket.predicted_sum += float(predicted_confidence)

    def record_correction(
        self,
        *,
        field_id: str,
        predicted_value: str,
        verified_value: str,
        engine_source: str,
        field_type: str,
        confidence_at_time: float,
        user_corrected_at: str | None = None,
    ) -> None:
        self.record_verification(
            engine_source,
            predicted_confidence=confidence_at_time,
            actual_correct=predicted_value == verified_value,
        )
        if self.store is not None:
            self.store.record_correction(
                predicted=predicted_value,
                verified=verified_value,
                engine=engine_source,
                confidence=confidence_at_time,
                field_id=field_id,
                field_type=field_type,
                user_corrected_at=user_corrected_at,
            )

    def calibrated_reliability(self, source_key: str, *, field_type: str = "generic") -> float:
        if self.store is not None:
            persisted = self.store.get_reliability(source_key, field_type)
            if persisted != 1.0:
                return persisted
        bucket = self._buckets.get(source_key)
        if bucket is None:
            return 1.0
        predicted = bucket.predicted_confidence
        actual = bucket.actual_correctness
        if predicted <= 0:
            return actual
        return max(0.1, min(1.25, actual / predicted))

    def is_overconfident(self, *, predicted_confidence: float, actual_correctness: float) -> bool:
        return float(predicted_confidence) - float(actual_correctness) >= 0.10

    def calibrate_confidence(
        self,
        predicted_confidence: float,
        *,
        source_keys: tuple[str, ...],
        field_type: str = "generic",
    ) -> float:
        if not source_keys:
            return round(float(predicted_confidence), 3)
        factor = sum(self.calibrated_reliability(source_key, field_type=field_type) for source_key in source_keys) / len(source_keys)
        return round(max(0.0, min(1.0, float(predicted_confidence) * factor)), 3)

    def snapshot(self) -> dict[str, object]:
        payload = {
            source_key: {
                "total": bucket.total,
                "correct": bucket.correct,
                "predicted_confidence": round(bucket.predicted_confidence, 3),
                "actual_correctness": round(bucket.actual_correctness, 3),
                "calibrated_reliability": round(self.calibrated_reliability(source_key), 3),
            }
            for source_key, bucket in sorted(self._buckets.items())
        }
        if self.store is not None:
            payload["persistent_report"] = self.store.get_confident_vs_correct()
        return payload
