from __future__ import annotations

from ocring.ocr.candidate_set import CandidateSet


def test_candidate_set_keeps_top_k_candidates() -> None:
    candidates = CandidateSet(top_k=3)
    candidates.add_candidate(candidate_value="A", candidate_score=0.4, source_lineage=("a",), reason="first")
    candidates.add_candidate(candidate_value="B", candidate_score=0.8, source_lineage=("b",), reason="second")
    candidates.add_candidate(candidate_value="C", candidate_score=0.6, source_lineage=("c",), reason="third")
    candidates.add_candidate(candidate_value="D", candidate_score=0.9, source_lineage=("d",), reason="fourth")

    values = [item.candidate_value for item in candidates.as_list()]

    assert values == ["D", "B", "C"]
    assert candidates.collapse().candidate_value == "D"
