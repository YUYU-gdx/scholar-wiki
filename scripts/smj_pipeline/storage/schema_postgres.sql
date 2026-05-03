CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  doi TEXT NOT NULL DEFAULT '',
  offline_html_path TEXT NOT NULL DEFAULT '',
  article_url TEXT NOT NULL DEFAULT '',
  publication_date TEXT NOT NULL DEFAULT '',
  online_date TEXT NOT NULL DEFAULT '',
  publication_year INTEGER,
  paper_citation_count INTEGER,
  metadata_source TEXT NOT NULL DEFAULT 'unknown',
  extractability_status TEXT NOT NULL DEFAULT '',
  paper_type TEXT NOT NULL DEFAULT '',
  extractability_reason TEXT NOT NULL DEFAULT '',
  extractability_evidence_section TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS paper_domains (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS canonical_variables (
  canonical_var_id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variable_aliases (
  id BIGSERIAL PRIMARY KEY,
  canonical_var_id TEXT NOT NULL,
  alias_text TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'unknown',
  paper_id TEXT,
  UNIQUE(canonical_var_id, alias_norm)
);

CREATE TABLE IF NOT EXISTS variable_definitions (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  variable_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  definition_text TEXT NOT NULL,
  measurement_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS direct_effects (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  source_canonical_var_id TEXT NOT NULL,
  target_canonical_var_id TEXT NOT NULL,
  source_alias_json TEXT NOT NULL DEFAULT '[]',
  target_alias_json TEXT NOT NULL DEFAULT '[]',
  effect_form TEXT NOT NULL,
  theory_name TEXT NOT NULL DEFAULT '',
  verification TEXT NOT NULL,
  evidence_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moderations (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  moderator_var TEXT NOT NULL,
  moderator_canonical_var_id TEXT NOT NULL,
  moderator_alias_json TEXT NOT NULL DEFAULT '[]',
  source_var TEXT NOT NULL DEFAULT '',
  target_var TEXT NOT NULL DEFAULT '',
  source_canonical_var_id TEXT NOT NULL DEFAULT '',
  target_canonical_var_id TEXT NOT NULL DEFAULT '',
  effect_form TEXT NOT NULL,
  theory_name TEXT NOT NULL DEFAULT '',
  verification TEXT NOT NULL,
  evidence_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactions (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  output_var TEXT NOT NULL,
  output_canonical_var_id TEXT NOT NULL,
  effect_form TEXT NOT NULL,
  theory_name TEXT NOT NULL DEFAULT '',
  verification TEXT NOT NULL,
  evidence_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interaction_inputs (
  id BIGSERIAL PRIMARY KEY,
  interaction_id BIGINT NOT NULL,
  input_var TEXT NOT NULL,
  input_canonical_var_id TEXT NOT NULL,
  input_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_papers_publication_year ON papers(publication_year);
CREATE INDEX IF NOT EXISTS idx_direct_effects_paper_id ON direct_effects(paper_id);
CREATE INDEX IF NOT EXISTS idx_direct_effects_pair ON direct_effects(source_canonical_var_id, target_canonical_var_id);
CREATE INDEX IF NOT EXISTS idx_moderations_paper_id ON moderations(paper_id);
CREATE INDEX IF NOT EXISTS idx_interactions_paper_id ON interactions(paper_id);
CREATE INDEX IF NOT EXISTS idx_interaction_inputs_interaction_id ON interaction_inputs(interaction_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  default_mode TEXT NOT NULL DEFAULT 'agent',
  library_id TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  deleted_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'fast',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  citations_json TEXT NOT NULL DEFAULT '[]',
  retrieval_json TEXT NOT NULL DEFAULT '{}',
  tool_trace_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'completed',
  error_detail TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_events (
  event_id BIGSERIAL PRIMARY KEY,
  message_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_events_message_id ON chat_events(message_id, event_id);
