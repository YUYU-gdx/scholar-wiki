# SMJ Extraction MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable extraction MVP for local SMJ fulltext papers that outputs variable relations, effect direction/strength, hypothesis verification, two theory-grounding categories, and citation edges into PostgreSQL + Neo4j.

**Architecture:** Use a hybrid pipeline: rule-based localization for main-model evidence, LLM normalization into strict schemas, then rule validation and storage. Keep PostgreSQL as source-of-truth and project graph-ready relations into Neo4j. Skip OCR and skip partial documents (abstract+references only).

**Tech Stack:** Python 3.12, `uv`, `pytest`, `sqlite` (local MVP dev harness), PostgreSQL, Neo4j, existing `scripts/smj_pipeline` codebase.

---

### Task 1: Data Contracts and Typed Schemas

**Files:**
- Create: `scripts/smj_pipeline/extraction/schemas.py`
- Create: `tests/test_extraction_schemas.py`
- Modify: `pyproject.toml` (only if schema libs are added)

- [ ] **Step 1: Write failing schema tests**

```python
from scripts.smj_pipeline.extraction.schemas import RelationRecord

def test_relation_requires_main_model():
    RelationRecord(
        paper_id="p1", source_var="A", target_var="B",
        relation_type="direct", direction="positive",
        model_tag="robustness"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_extraction_schemas.py::test_relation_requires_main_model`  
Expected: FAIL with import/validation errors.

- [ ] **Step 3: Implement strict schemas**

```python
class RelationRecord(BaseModel):
    model_tag: Literal["main_model"]
    direction: Literal["positive","negative","u_shape","inverted_u","non_significant"]
    verification: Literal["supported","partially_supported","not_supported"]
```

- [ ] **Step 4: Re-run schema tests**

Run: `uv run pytest -q tests/test_extraction_schemas.py`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/extraction/schemas.py tests/test_extraction_schemas.py pyproject.toml
git commit -m "feat: add extraction schemas with strict constraints"
```

### Task 2: Document Qualification (A/B/C Classification)

**Files:**
- Create: `scripts/smj_pipeline/extraction/qualifier.py`
- Create: `tests/test_extraction_qualifier.py`

- [ ] **Step 1: Write failing qualification tests**

```python
def test_abstract_only_is_class_b():
    html = "<section>Abstract</section><section>References</section>"
    assert classify_document(html).doc_class == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_extraction_qualifier.py::test_abstract_only_is_class_b -v`  
Expected: FAIL.

- [ ] **Step 3: Implement qualification rules**

```python
def is_class_a(doc):  # has hypotheses/results and main-model signal
    ...
```

- [ ] **Step 4: Run all qualifier tests**

Run: `uv run pytest -q tests/test_extraction_qualifier.py`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/extraction/qualifier.py tests/test_extraction_qualifier.py
git commit -m "feat: add A/B/C document qualification rules"
```

### Task 3: Main-Model Evidence Locator

**Files:**
- Create: `scripts/smj_pipeline/extraction/locator.py`
- Create: `tests/test_extraction_locator.py`

- [ ] **Step 1: Write failing tests for section/table localization**
- [ ] **Step 2: Run locator tests and confirm fail**

Run: `uv run pytest -q tests/test_extraction_locator.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement minimal locator**

```python
def locate_main_model_evidence(doc) -> list[EvidenceSpan]:
    # prioritize hypotheses/results + main model tables
    ...
```

- [ ] **Step 4: Re-run locator tests**

Run: `uv run pytest -q tests/test_extraction_locator.py`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/extraction/locator.py tests/test_extraction_locator.py
git commit -m "feat: add main-model evidence locator"
```

### Task 4: Structured Extraction (Hybrid Normalization Interface)

**Files:**
- Create: `scripts/smj_pipeline/extraction/extractor.py`
- Create: `scripts/smj_pipeline/extraction/prompts.py`
- Create: `tests/test_extraction_extractor.py`

- [ ] **Step 1: Write failing parser-normalization tests**
- [ ] **Step 2: Run tests and confirm fail**

Run: `uv run pytest -q tests/test_extraction_extractor.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement extractor interface**

```python
def extract_records(evidence_spans, llm_client) -> ExtractionBundle:
    # returns relations, theory grounding (2 types), hypotheses, citations
    ...
```

- [ ] **Step 4: Add deterministic fixture-based tests (no network)**
- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/extraction/extractor.py scripts/smj_pipeline/extraction/prompts.py tests/test_extraction_extractor.py
git commit -m "feat: add hybrid extraction interface and fixtures"
```

### Task 5: Validation and Review Queue

**Files:**
- Create: `scripts/smj_pipeline/extraction/validator.py`
- Create: `scripts/smj_pipeline/extraction/review_queue.py`
- Create: `tests/test_extraction_validator.py`

- [ ] **Step 1: Write failing validation tests**

```python
def test_reject_relation_without_evidence():
    ...
```

- [ ] **Step 2: Run validation tests and confirm fail**

Run: `uv run pytest -q tests/test_extraction_validator.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement validation gates**
- [ ] **Step 4: Implement review queue output writer (CSV/JSONL)**
- [ ] **Step 5: Re-run tests and commit**

```bash
git add scripts/smj_pipeline/extraction/validator.py scripts/smj_pipeline/extraction/review_queue.py tests/test_extraction_validator.py
git commit -m "feat: add extraction validation gates and review queue"
```

### Task 6: Storage Layer (PostgreSQL + Neo4j)

**Files:**
- Create: `scripts/smj_pipeline/storage/postgres_repo.py`
- Create: `scripts/smj_pipeline/storage/neo4j_repo.py`
- Create: `scripts/smj_pipeline/storage/schema.sql`
- Create: `tests/test_storage_postgres_repo.py`
- Create: `tests/test_storage_neo4j_repo.py`

- [ ] **Step 1: Write failing repository tests (mocks/stubs for Neo4j)**
- [ ] **Step 2: Run tests and confirm fail**

Run: `uv run pytest -q tests/test_storage_postgres_repo.py tests/test_storage_neo4j_repo.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement PostgreSQL writes as source-of-truth**
- [ ] **Step 4: Implement Neo4j projection writers**
- [ ] **Step 5: Re-run tests and commit**

```bash
git add scripts/smj_pipeline/storage tests/test_storage_postgres_repo.py tests/test_storage_neo4j_repo.py
git commit -m "feat: add postgres source-of-truth and neo4j projection repositories"
```

### Task 7: End-to-End CLI for 100-Paper Baseline

**Files:**
- Create: `scripts/smj_pipeline/run_extraction_mvp.py`
- Create: `tests/test_run_extraction_mvp.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests (A-class only, B skipped, sample denominator=100)**
- [ ] **Step 2: Run CLI tests and confirm fail**

Run: `uv run pytest -q tests/test_run_extraction_mvp.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement CLI orchestration**

```python
def run(input_manifest, sample_size=100):
    # classify -> locate -> extract -> validate -> store
    # skip class B and do not count in denominator
    ...
```

- [ ] **Step 4: Re-run tests**
- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/run_extraction_mvp.py tests/test_run_extraction_mvp.py README.md
git commit -m "feat: add end-to-end extraction MVP runner"
```

### Task 8: Metrics and Acceptance Report

**Files:**
- Create: `scripts/smj_pipeline/evaluation/metrics.py`
- Create: `scripts/smj_pipeline/evaluation/report_template.md`
- Create: `tests/test_evaluation_metrics.py`
- Create: `outputs/smj_extraction_mvp/` (runtime output)

- [ ] **Step 1: Write failing metric tests**
- [ ] **Step 2: Run tests and confirm fail**

Run: `uv run pytest -q tests/test_evaluation_metrics.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement acceptance metrics**
- [ ] **Step 4: Generate report from a baseline run**
- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/evaluation tests/test_evaluation_metrics.py
git commit -m "feat: add extraction MVP metrics and acceptance reporting"
```

## Global Verification Checklist (Before Execution Close)

- [ ] Run unit test suite: `uv run pytest -q tests`
- [ ] Run focused e2e baseline: `uv run python scripts/smj_pipeline/run_extraction_mvp.py --sample-size 100`
- [ ] Confirm Class B skipped and excluded from denominator
- [ ] Confirm all saved relations have evidence anchors
- [ ] Confirm PostgreSQL and Neo4j record counts reconcile for projected entities
- [ ] Export acceptance report to `outputs/smj_extraction_mvp/acceptance_report.md`

