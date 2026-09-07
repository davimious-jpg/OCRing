from __future__ import annotations

from ocring.ocr.independence import EvidenceLineageDag, build_default_lineage


def test_lineage_counts_only_genuinely_independent_sources() -> None:
    dag = EvidenceLineageDag()
    dag.add_node("frame:f1:pixels", kind="frame_pixels", source_group="frame:f1")
    dag.add_node("ocr:c1", kind="classic_ocr", source_group="frame:f1", parent_ids=("frame:f1:pixels",))
    dag.add_node("dictionary:c1", kind="dictionary_matcher", source_group="frame:f1", parent_ids=("ocr:c1",))
    dag.add_node("local_ai:c1", kind="local_ai_correction", source_group="frame:f1", parent_ids=("ocr:c1",))

    assert dag.count_independent_sources(("dictionary:c1", "local_ai:c1")) == 1


def test_default_lineage_keeps_dictionary_and_local_ai_correlated_to_same_frame() -> None:
    dag, selected_nodes = build_default_lineage(
        frame_id="f1",
        crop_id="crop-1",
        engine_name="classic_ocr",
        candidate_value="Power Bore",
        include_dictionary_matcher=True,
        include_local_ai=True,
    )

    assert dag.count_independent_sources(selected_nodes) == 1
