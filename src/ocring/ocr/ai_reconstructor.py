from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re


@dataclass(frozen=True)
class ReconstructionResult:
    repaired_fragments: tuple[str, ...]
    confidence: float
    status: str
    provenance: dict[str, object] = field(default_factory=dict)


class AIReconstructor:
    def reconstruct(
        self,
        fragments: tuple[str, ...] | list[str],
        *,
        allowed_terms: tuple[str, ...] | list[str] = (),
    ) -> ReconstructionResult:
        cleaned = tuple(fragment.strip() for fragment in fragments if str(fragment).strip())
        if not cleaned:
            return ReconstructionResult((), 0.0, "NEEDS_REVIEW", {"engine_source": "classic_ocr_fallback", "reason": "NO_FRAGMENTS"})

        normalized_terms = {term: _normalize(term) for term in allowed_terms if str(term).strip()}
        consumed: set[int] = set()
        repaired: list[str] = []
        scores: list[float] = []

        for term, normalized_term in normalized_terms.items():
            best_window = _best_window(cleaned, normalized_term, consumed)
            if best_window is None:
                continue
            start, end, score = best_window
            if score < 0.84:
                continue
            repaired.append(term)
            scores.append(score)
            consumed.update(range(start, end + 1))

        fallback_tokens = [token for index, token in enumerate(cleaned) if index not in consumed]
        if fallback_tokens:
            grouped_fallback = _group_fallback_tokens(tuple(fallback_tokens))
            repaired.extend(grouped_fallback)
            scores.extend(_fallback_scores(grouped_fallback))

        repaired = _dedupe_preserve_order(repaired)
        confidence = round(sum(scores) / len(scores), 3) if scores else 0.0
        status = "REPAIRED" if confidence >= 0.74 else "NEEDS_REVIEW"
        engine_source = "local_ai_correction" if status == "REPAIRED" else "classic_ocr_fallback"
        return ReconstructionResult(
            tuple(repaired),
            confidence,
            status,
            {
                "engine_source": engine_source,
                "allowed_term_count": len(normalized_terms),
                "fragment_count": len(cleaned),
            },
        )


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _best_window(fragments: tuple[str, ...], normalized_term: str, consumed: set[int]) -> tuple[int, int, float] | None:
    best: tuple[int, int, float] | None = None
    max_window = min(4, len(fragments))
    for window_size in range(1, max_window + 1):
        for start in range(0, len(fragments) - window_size + 1):
            end = start + window_size - 1
            if any(index in consumed for index in range(start, end + 1)):
                continue
            joined = _normalize("".join(fragments[start : end + 1]))
            if not joined:
                continue
            score = SequenceMatcher(None, joined, normalized_term).ratio()
            if best is None or score > best[2]:
                best = (start, end, score)
    return best


def _group_fallback_tokens(fragments: tuple[str, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    current: list[str] = []
    for token in fragments:
        token_type = _token_type(token)
        if not current:
            current.append(token)
            continue
        if _token_type(current[-1]) == token_type == "alpha":
            current.append(token)
            continue
        groups.append(" ".join(current))
        current = [token]
    if current:
        groups.append(" ".join(current))
    return tuple(groups)


def _token_type(token: str) -> str:
    if token.isdigit():
        return "digit"
    if re.fullmatch(r"[ivx]+", token.lower()):
        return "roman"
    return "alpha"


def _fallback_scores(groups: tuple[str, ...]) -> list[float]:
    scores: list[float] = []
    for group in groups:
        token_count = len(group.split())
        if token_count >= 2:
            scores.append(0.72)
        else:
            scores.append(0.58)
    return scores


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output
