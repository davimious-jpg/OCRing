from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    kind: str
    source_group: str
    parent_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceLineageDag:
    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}

    def add_node(
        self,
        node_id: str,
        *,
        kind: str,
        source_group: str,
        parent_ids: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceNode:
        node = EvidenceNode(
            node_id=node_id,
            kind=kind,
            source_group=source_group,
            parent_ids=parent_ids,
            metadata=dict(metadata or {}),
        )
        self._nodes[node_id] = node
        return node

    def get_node(self, node_id: str) -> EvidenceNode:
        return self._nodes[node_id]

    def ancestors(self, node_id: str) -> tuple[EvidenceNode, ...]:
        seen: set[str] = set()
        ordered: list[EvidenceNode] = []

        def visit(current_id: str) -> None:
            for parent_id in self._nodes.get(current_id, EvidenceNode("", "", "", ())).parent_ids:
                if parent_id in seen or parent_id not in self._nodes:
                    continue
                seen.add(parent_id)
                ordered.append(self._nodes[parent_id])
                visit(parent_id)

        visit(node_id)
        return tuple(ordered)

    def count_independent_sources(self, node_ids: tuple[str, ...]) -> int:
        groups = {group for group in self.independent_source_groups(node_ids)}
        return len(groups)

    def independent_source_groups(self, node_ids: tuple[str, ...]) -> tuple[str, ...]:
        groups: list[str] = []
        for node_id in node_ids:
            if node_id not in self._nodes:
                continue
            node = self._nodes[node_id]
            roots = [ancestor for ancestor in self.ancestors(node_id) if not ancestor.parent_ids]
            if not roots:
                roots = [node]
            for root in roots:
                if root.source_group not in groups:
                    groups.append(root.source_group)
        return tuple(groups)

    def as_dict(self) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": node.node_id,
                    "kind": node.kind,
                    "source_group": node.source_group,
                    "parent_ids": list(node.parent_ids),
                    "metadata": node.metadata,
                }
                for node in self._nodes.values()
            ]
        }


def build_default_lineage(
    *,
    frame_id: str,
    crop_id: str,
    engine_name: str,
    candidate_value: str,
    include_dictionary_matcher: bool,
    include_local_ai: bool,
) -> tuple[EvidenceLineageDag, tuple[str, ...]]:
    dag = EvidenceLineageDag()
    pixel_node_id = f"frame:{frame_id}:pixels"
    dag.add_node(pixel_node_id, kind="frame_pixels", source_group=f"frame:{frame_id}")
    ocr_node_id = f"ocr:{crop_id}"
    dag.add_node(
        ocr_node_id,
        kind="classic_ocr",
        source_group=f"frame:{frame_id}",
        parent_ids=(pixel_node_id,),
        metadata={"engine_name": engine_name, "crop_id": crop_id},
    )
    selected_nodes = [ocr_node_id]
    if include_dictionary_matcher:
        dictionary_node_id = f"dictionary:{crop_id}:{candidate_value}"
        dag.add_node(
            dictionary_node_id,
            kind="dictionary_matcher",
            source_group=f"frame:{frame_id}",
            parent_ids=(ocr_node_id,),
            metadata={"candidate_value": candidate_value},
        )
        selected_nodes.append(dictionary_node_id)
    if include_local_ai:
        ai_node_id = f"local_ai:{crop_id}:{candidate_value}"
        dag.add_node(
            ai_node_id,
            kind="local_ai_correction",
            source_group=f"frame:{frame_id}",
            parent_ids=(ocr_node_id,),
            metadata={"candidate_value": candidate_value},
        )
        selected_nodes.append(ai_node_id)
    return dag, tuple(selected_nodes)
