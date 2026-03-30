CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL,
  source_var TEXT NOT NULL,
  target_var TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  model_tag TEXT NOT NULL,
  direction TEXT NOT NULL,
  verification TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL
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
