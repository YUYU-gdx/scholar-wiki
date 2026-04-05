CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS paper_domains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS canonical_variables (
  canonical_var_id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variable_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_var_id TEXT NOT NULL,
  alias_text TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'unknown',
  paper_id TEXT,
  UNIQUE(canonical_var_id, alias_norm)
);

CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  source_canonical_var_id TEXT NOT NULL DEFAULT '',
  target_canonical_var_id TEXT NOT NULL DEFAULT '',
  source_alias_text TEXT NOT NULL DEFAULT '',
  target_alias_text TEXT NOT NULL DEFAULT '',
  relation_type TEXT NOT NULL,
  model_tag TEXT NOT NULL,
  relation_form TEXT NOT NULL DEFAULT 'linear',
  direction TEXT NOT NULL,
  verification TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alias_mentions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  relation_row_id INTEGER NOT NULL,
  canonical_var_id TEXT NOT NULL,
  alias_text TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variable_theory_grounding (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  variable_name TEXT NOT NULL,
  theory TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relation_theory_grounding (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  theory TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  label TEXT NOT NULL,
  statement TEXT NOT NULL,
  verification TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  citation_key TEXT NOT NULL,
  source_text TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
);
