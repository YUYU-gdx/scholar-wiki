export interface GraphNode {
  id: string;
  library_id?: string;
  label?: string;
  name?: string;
  type?: string;
  x?: number;
  y?: number;
  z?: number;
  validated_variable?: boolean;
  relation_degree?: number;
  latest_concept?: string;
  latest_theories?: string[];
  latest_concept_source?: {
    paper_id?: string;
    publication_year?: number;
  };
  aliases?: string[];
  alias_count?: number;
  first_year?: number;
  canonical_var_id?: string;
  paper_count?: number;
  paper_profile?: Record<string, unknown>;
  dominant_paper_id?: string;
  paper_entropy?: number;
}

export interface GraphEdge {
  source: string | GraphNode;
  target: string | GraphNode;
  paper_id?: string;
  doi?: string;
  direction?: string;
  relation_form?: string;
  verification?: string;
  evidence_section?: string;
  evidence_snippet?: string;
  evidence_anchor?: string;
  display_effect_class?: string;
  hypothesis_label?: string;
  description?: string;
  strength?: number;
  paper_year?: number;
  relation_type_std?: string;
}

export interface ModerationLink {
  moderator_var: string;
  moderator_node_id: string;
  moderator_alias_json?: string[];
  moderated_relation: {
    source: string;
    target: string;
  };
  direction?: string;
  verification?: string;
  hypothesis_label?: string;
  evidence_section?: string;
  evidence_snippet?: string;
}

export interface InteractionLink {
  inputs: string[];
  input_node_ids: string[];
  output: string;
  output_node_id: string;
  interaction_type?: string;
  moderator?: string;
  moderator_node_id?: string;
  effect?: string;
  verification?: string;
  hypothesis_label?: string;
  evidence_section?: string;
  evidence_snippet?: string;
  description?: string;
}

export interface GraphOverview {
  meta: {
    paper_count?: number;
    node_count?: number;
    edge_count?: number;
    [key: string]: unknown;
  };
  nodes: GraphNode[];
  edges: GraphEdge[];
  moderation_links: ModerationLink[];
  interaction_links: InteractionLink[];
  isolated_nodes?: IsolatedNode[];
}

export interface GraphFull extends GraphOverview {
  paper_map: Record<string, PaperDetail>;
}

export interface IsolatedNode {
  node_id: string;
  label?: string;
  reason?: string;
}

export interface NeighborhoodResponse {
  node_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  moderation_links: ModerationLink[];
  interaction_links: InteractionLink[];
}

export interface SearchResult {
  id: string;
  kind: string;
  title?: string;
  score: number;
  [key: string]: unknown;
}

export interface SearchResponse {
  results: SearchResult[];
  search_meta: {
    vector_backend_requested?: string;
    vector_backend_used?: string;
    note?: string;
  };
}

export interface PaperDetail {
  paper_id: string;
  paper_id_raw?: string;
  paper_key?: string;
  library_id?: string;
  doi?: string;
  title?: string;
  display_title?: string;
  source_pdf_name?: string;
  source_md_path?: string;
  source_pdf_path?: string;
  offline_html_path?: string;
  article_url?: string;
  publication_date?: string;
  online_date?: string;
  publication_year?: number;
  paper_citation_count?: number;
  extractability_status?: string;
  paper_type?: string;
  extractability_reason?: string;
  extractability_evidence_section?: string;
  paper_domains?: string[];
  context_variables?: string[];
  operationalization?: Record<string, { operationalized_as: string[] }>;
  variable_definitions?: VariableDefinition[];
  main_effects?: MainEffect[];
  moderations?: ModerationLink[];
  interactions?: InteractionLink[];
  [key: string]: unknown;
}

export interface VariableDefinition {
  variable: string;
  aliases?: string[];
  definition?: string;
  definition_evidence_section?: string;
}

export interface MainEffect {
  from: string;
  to: string;
  direction?: string;
  effect?: string;
  hypothesis_label?: string;
  verification?: string;
  evidence_section?: string;
  evidence_snippet?: string;
  description?: string;
}

export interface VariableDetail {
  node: GraphNode;
  paper_count_total: number;
  paper_count_edge: number;
  paper_count_moderation: number;
  paper_count_interaction: number;
  papers: VariablePaper[];
  paper_groups: VariablePaperGroup[];
}

export interface VariablePaper {
  paper_id: string;
  doi?: string;
  mentions: unknown;
  [key: string]: unknown;
}

export interface VariablePaperGroup {
  paper_id: string;
  doi?: string;
  publication_year?: number;
  open_local_html?: string;
  open_online_url?: string;
  concepts: string[];
  measurement_methods: string[];
  relations: VariableRelation[];
}

export interface VariableRelation {
  type: 'direct_effect' | 'moderation' | 'interaction';
  direction?: string;
  source?: string;
  target?: string;
  verification?: string;
  [key: string]: unknown;
}

export interface ChatSession {
  session_id: string;
  title: string;
  default_mode: 'fast' | 'agent';
  library_id: string;
  created_at?: string;
  updated_at?: string;
}

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  status: 'running' | 'completed' | 'failed';
  citations?: Citation[];
  retrieval?: Record<string, unknown>;
  tool_trace?: ToolCall[];
  error_detail?: string;
  created_at?: string;
}

export interface Citation {
  id?: string;
  paper_id?: string;
  title?: string;
  sentence?: string;
  paragraph?: string;
  [key: string]: unknown;
}

export interface ToolCall {
  name?: string;
  arguments?: string;
  result?: string;
  [key: string]: unknown;
}

export interface SendMessageResponse {
  session_id: string;
  assistant_message_id: string;
  user_message_id: string;
  stream_url: string;
}

export interface SSEEvent {
  type: string;
  data: string;
}

export interface PipelineJob {
  job_id: string;
  display_name?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  status_code?: string;
  stage?: string;
  stage_code?: string;
  stage_label?: string;
  progress?: number;
  library_id: string;
  workspace_path?: string;
  input_path?: string;
  output_path?: string;
  error_code?: string;
  error_detail?: string;
  can_cancel?: boolean;
  can_retry?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PipelineJobList {
  jobs: PipelineJob[];
  total: number;
  page: number;
  page_size: number;
}

export interface LiteratureLibrary {
  library_id: string;
  paper_count: number;
  updated_at: string;
  path: string;
}

export interface LibrariesResponse {
  libraries: LiteratureLibrary[];
  default_library_id: string;
}

export interface LiteratureSearchHit {
  paper_id?: string;
  doi?: string;
  title?: string;
  sentence?: string;
  paragraph?: string;
  score?: number;
  [key: string]: unknown;
}

export interface LiteratureSearchResponse {
  query: string;
  library_id: string;
  top_k: number;
  levels: string[];
  keyword_hits: LiteratureSearchHit[];
  rag_hits: LiteratureSearchHit[];
  merged_hits: LiteratureSearchHit[];
  degraded?: boolean;
  degraded_reason?: string;
  search_meta?: Record<string, unknown>;
}

export interface LiteratureAnswerResponse {
  answer: string;
  citations: Citation[];
  retrieval: {
    merged_hits: LiteratureSearchHit[];
    [key: string]: unknown;
  };
}

export interface WorkspaceLayout {
  name: string;
  layout: Record<string, unknown>;
}

export type View = 'library' | 'graph' | 'chat' | 'reader' | 'pipeline';
