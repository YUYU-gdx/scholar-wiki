CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  doi TEXT NOT NULL DEFAULT '',
  offline_html_path TEXT NOT NULL DEFAULT '',
  article_url TEXT NOT NULL DEFAULT '',
  publication_date TEXT NOT NULL DEFAULT '',
  online_date TEXT NOT NULL DEFAULT '',
  publication_year INTEGER,
  paper_citation_count INTEGER,
  metadata_source TEXT NOT NULL DEFAULT 'unknown'
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

CREATE TABLE IF NOT EXISTS relations (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  source_canonical_var_id TEXT NOT NULL DEFAULT '',
  target_canonical_var_id TEXT NOT NULL DEFAULT '',
  source_alias_text TEXT NOT NULL DEFAULT '',
  target_alias_text TEXT NOT NULL DEFAULT '',
  unresolved_abbr BOOLEAN NOT NULL DEFAULT FALSE,
  abbr_form TEXT NOT NULL DEFAULT '',
  name_resolution_source TEXT NOT NULL DEFAULT '',
  relation_type TEXT NOT NULL,
  relation_type_raw TEXT NOT NULL DEFAULT '',
  relation_type_std TEXT NOT NULL DEFAULT 'unspecified',
  model_tag TEXT NOT NULL,
  relation_form TEXT NOT NULL DEFAULT 'linear',
  direction TEXT NOT NULL,
  verification TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL,
  moderator_var TEXT NOT NULL DEFAULT '',
  mediator_var TEXT NOT NULL DEFAULT '',
  condition_text TEXT NOT NULL DEFAULT '',
  moderated_source_var TEXT NOT NULL DEFAULT '',
  moderated_target_var TEXT NOT NULL DEFAULT '',
  moderated_hypothesis_label TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alias_mentions (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  relation_row_id BIGINT NOT NULL,
  canonical_var_id TEXT NOT NULL,
  alias_text TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variable_theory_grounding (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  variable_name TEXT NOT NULL,
  theory TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation_theory_grounding (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  theory TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  label TEXT NOT NULL,
  statement TEXT NOT NULL,
  verification TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
  id BIGSERIAL PRIMARY KEY,
  paper_id TEXT NOT NULL,
  citation_key TEXT NOT NULL,
  source_text TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_pair ON relations(source_canonical_var_id, target_canonical_var_id);
CREATE INDEX IF NOT EXISTS idx_relations_paper_id ON relations(paper_id);
CREATE INDEX IF NOT EXISTS idx_papers_publication_year ON papers(publication_year);
CREATE INDEX IF NOT EXISTS idx_citations_paper_id ON citations(paper_id);
