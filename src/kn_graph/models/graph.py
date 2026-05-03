from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    name: str = ""
    type: str = ""
    validated_variable: bool = False
    relation_degree: int = 0
    is_isolated: bool = False
    latest_concept: str = ""
    latest_concept_source: dict[str, Any] = {}
    latest_theories: list[str] = []
    library_name: str = ""


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = ""
    target: str = ""
    label: str = ""
    relation_type: str = ""
    relation_type_std: str = ""
    relation_type_raw: str = ""
    effect_form: str = ""
    source_name: str = ""
    target_name: str = ""
    source_name_local: str = ""
    target_name_local: str = ""
    source_name_canonical: str = ""
    target_name_canonical: str = ""
    theory_name: str = ""
    evidence_text: str = ""
    paper_id: str = ""
    doi: str = ""


class ModerationLink(BaseModel):
    model_config = ConfigDict(extra="ignore")

    moderator_node_id: str = ""
    moderator_var: str = ""
    paper_id: str = ""
    doi: str = ""
    moderated_relation: Optional[dict[str, Any]] = None
    effect_form: str = ""
    theory_name: str = ""
    evidence_text: str = ""


class InteractionLink(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_node_ids: list[str] = []
    output_node_id: str = ""
    inputs: list[str] = []
    output: str = ""
    effect_form: str = ""
    theory_name: str = ""
    paper_id: str = ""
    doi: str = ""
    evidence_text: str = ""


class IsolatedNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    label: str
    reason: str = ""


class GraphMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    isolated_node_count: int = 0
    dataset_library_name: str = ""


class GraphOverview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meta: GraphMeta = GraphMeta()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    moderation_links: list[ModerationLink] = []
    interaction_links: list[InteractionLink] = []
    isolated_nodes: list[IsolatedNode] = []


class GraphFull(GraphOverview):
    paper_map: dict[str, Any] = {}


class GraphSearchParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = ""
    mode: str = "variable"
    limit: int = 20
    keyword_weight: float = 0.5
    vector_weight: float = 0.5
    vector_backend: str = "hash"


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = ""
    id: str = ""
    title: str = ""
    score: float = 0.0
    predecessors: list[str] = []
    successors: list[str] = []
    papers: list[str] = []
    doi: str = ""
    paper_id: str = ""
    publication_year: Optional[int] = None
    open_local_html: str = ""
    open_online_url: str = ""
    relations: list[str] = []


class SearchMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vector_backend_requested: str = ""
    vector_backend_used: str = "hash"
    note: str = ""


class GraphSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[SearchResult] = []
    search_meta: SearchMeta = SearchMeta()


class NeighborhoodParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    hops: int = 1
    limit_nodes: int = 350
    limit_edges: int = 900


class NeighborhoodResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str = ""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    moderation_links: list[ModerationLink] = []
    interaction_links: list[InteractionLink] = []


class PaperDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paper_id: str = ""
    doi: str = ""
    title: str = ""
    publication_year: Optional[int] = None
    article_url: str = ""
    offline_html_path: str = ""
    variable_definitions: list[dict[str, Any]] = []
    direct_effects: list[dict[str, Any]] = []
    interactions: list[dict[str, Any]] = []
    paper_domains: list[str] = []


class VariablePaperItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paper_id: str = ""
    doi: str = ""
    publication_year: Optional[int] = None
    open_local_html: str = ""
    open_online_url: str = ""
    mentions: list[dict[str, Any]] = []


class VariablePaperGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paper_id: str = ""
    doi: str = ""
    publication_year: Optional[int] = None
    open_local_html: str = ""
    open_online_url: str = ""
    concepts: list[dict[str, Any]] = []
    measurement_methods: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []


class VariableDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node: dict[str, Any] = {}
    paper_count_total: int = 0
    paper_count_edge: int = 0
    paper_count_moderation: int = 0
    paper_count_interaction: int = 0
    paper_count: int = 0
    papers: list[VariablePaperItem] = []
    paper_groups: list[VariablePaperGroup] = []
    mentions: list[dict[str, Any]] = []