# Variable Concept Embedding & MCP Semantic Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 pipeline agent 抽取入库后，同步构建“变量概念向量索引”，并新增 MCP 概念召回工具（默认 `top_k=5`），召回后基于 `canonical_variables + variable_aliases` 扩展返回所有同名/别名变量对应论文。

**Architecture:** 新增一个独立的变量概念索引服务（复用现有 Chroma 实现模式），在 `pipeline_runtime` finalize 链路中调用同步函数写入 `{workspace}/corpus/variables_concept_index/`。MCP 新增 `graph_variable_concept_search`：先查概念向量索引，再用 canonical/alias 表扩展变量集合并聚合论文返回。

**Tech Stack:** Python 3, `kn_graph.services.literature_service.ChromaDBClient` 模式, SQLite (`kn_gragh.db`), FastAPI backend + MCP stdio server。

---

## File Structure

**Create**
- `src/kn_graph/services/variable_concept_index.py`
- `scripts/smj_pipeline/backfill_variable_concept_index.py`
- `tests/test_variable_concept_index.py`
- `tests/test_kn_mcp_variable_concept_search.py`
- `tests/test_pipeline_variable_concept_index.py`

**Modify**
- `src/kn_graph/services/pipeline_runtime.py`
- `scripts/smj_pipeline/kn_mcp_server.py`

**Reference (read-only during implementation)**
- `src/kn_graph/services/literature_service.py`
- `src/kn_graph/services/sqlite_repo.py`
- `src/kn_graph/services/schema.sql`

---

### Task 1: Build Variable Concept Index Service

**Files:**
- Create: `src/kn_graph/services/variable_concept_index.py`
- Test: `tests/test_variable_concept_index.py`

- [ ] **Step 1: Write the failing service test for upsert + query + alias expansion contract**

```python
# tests/test_variable_concept_index.py

def test_upsert_and_query_returns_doc_level_hits(tmp_path):
    # arrange: temp workspace + sqlite with variable_definitions/canonical/aliases
    # act: upsert concepts for one paper; query by concept
    # assert: hit contains paper_id, variable_name_norm, canonical_var_id
    assert False, "implement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_variable_concept_index.py -q`
Expected: FAIL with assertion/import errors.

- [ ] **Step 3: Implement minimal index service**

```python
# src/kn_graph/services/variable_concept_index.py
class VariableConceptIndexService:
    def __init__(self, workspace_path: str): ...
    def upsert_paper_variable_concepts(self, *, library_id: str, paper_id: str, db_path: str) -> dict: ...
    def query(self, *, library_id: str, query: str, top_k: int = 5) -> list[dict]: ...
    def expand_aliases(self, *, db_path: str, canonical_var_ids: list[str]) -> dict[str, list[str]]: ...
```

Implementation notes:
- Persist dir: `{workspace}/corpus/variables_concept_index/`
- Collection: `variable_concepts_v1`
- doc id: `{library_id}::{paper_id}::{variable_name_norm}`
- Use only `canonical_variables + variable_aliases` for alias expansion.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_variable_concept_index.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_variable_concept_index.py src/kn_graph/services/variable_concept_index.py
git commit -m "feat: add variable concept index service"
```

---

### Task 2: Wire Pipeline Finalize Sync

**Files:**
- Modify: `src/kn_graph/services/pipeline_runtime.py`
- Test: `tests/test_pipeline_variable_concept_index.py`

- [ ] **Step 1: Write failing pipeline test for concept sync invocation**

```python
# tests/test_pipeline_variable_concept_index.py

def test_finalize_after_import_syncs_variable_concept_index(mocker, tmp_path):
    # mock import success + sqlite data
    # assert sync called and result contains concept_index_result
    assert False, "implement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_pipeline_variable_concept_index.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement finalize integration**

Code changes:
- In `_run_finalize_after_import(...)` and `_run_finalize(...)`, after sqlite import success:
  - call `VariableConceptIndexService(...).upsert_paper_variable_concepts(...)`
  - append `concept_index_result` to result payload
  - on exception set `concept_index_warning` and continue

Required result payload fields:
- `concept_index_result` (dict)
- `concept_index_warning` (string, optional)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_pipeline_variable_concept_index.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline_variable_concept_index.py src/kn_graph/services/pipeline_runtime.py
git commit -m "feat: sync variable concept index after pipeline import"
```

---

### Task 3: Add MCP Tool `graph_variable_concept_search`

**Files:**
- Modify: `scripts/smj_pipeline/kn_mcp_server.py`
- Test: `tests/test_kn_mcp_variable_concept_search.py`

- [ ] **Step 1: Write failing MCP test for new tool schema and default top_k**

```python
# tests/test_kn_mcp_variable_concept_search.py

def test_tool_list_contains_graph_variable_concept_search():
    assert False, "implement"

def test_graph_variable_concept_search_default_top_k_is_5():
    assert False, "implement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_kn_mcp_variable_concept_search.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement tool + handler**

In `scripts/smj_pipeline/kn_mcp_server.py`:
- Add tool spec in `_build_tools()`:
  - name: `graph_variable_concept_search`
  - args: `query` required, `top_k` optional, `library_id` optional
- Add handler `_handle_graph_variable_concept_search(...)`:
  1. resolve library scope
  2. query variable concept index top_k (default 5)
  3. canonical id set -> alias expansion from sqlite
  4. aggregate papers for alias group
  5. return `matched_variables`, `papers`, `trace`
- Add switch in `_call_tool(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_kn_mcp_variable_concept_search.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_kn_mcp_variable_concept_search.py scripts/smj_pipeline/kn_mcp_server.py
git commit -m "feat: add mcp graph_variable_concept_search tool"
```

---

### Task 4: Add Historical Backfill Script

**Files:**
- Create: `scripts/smj_pipeline/backfill_variable_concept_index.py`
- Test: `tests/test_variable_concept_index.py` (append integration case)

- [ ] **Step 1: Write failing test for idempotent backfill summary**

```python
# append in tests/test_variable_concept_index.py

def test_backfill_idempotent_counts(tmp_path):
    # run backfill twice
    # second run should not duplicate docs
    assert False, "implement"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_variable_concept_index.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement backfill CLI**

```python
# scripts/smj_pipeline/backfill_variable_concept_index.py
# args: --library-id (optional), --all
# output: processed/inserted/updated/skipped/errors per library
```

Behavior:
- discover libraries from registry/workspaces
- for each library, iterate papers from sqlite and call upsert
- print JSON summary to stdout

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_variable_concept_index.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/smj_pipeline/backfill_variable_concept_index.py tests/test_variable_concept_index.py
git commit -m "feat: add backfill command for variable concept index"
```

---

### Task 5: End-to-End Regression & Contract Checks

**Files:**
- Modify (if needed): `tests/test_agent_extraction.py` or `tests/test_async_pipeline_execution.py`
- Modify (if needed): `tests/test_user_journey_contract.py`

- [ ] **Step 1: Add/adjust contract assertions**

Add assertions:
- pipeline result includes `concept_index_result` (or warning)
- MCP tool list includes `graph_variable_concept_search`
- default `top_k=5` behavior verified

- [ ] **Step 2: Run focused test suite**

Run:
- `uv run python -m pytest tests/test_variable_concept_index.py -q`
- `uv run python -m pytest tests/test_pipeline_variable_concept_index.py -q`
- `uv run python -m pytest tests/test_kn_mcp_variable_concept_search.py -q`
- `uv run python -m pytest tests/test_agent_extraction.py -q`

Expected: PASS.

- [ ] **Step 3: Run broader regression slice**

Run:
- `uv run python -m pytest tests/test_async_pipeline_execution.py -q`
- `uv run python -m pytest tests/test_user_journey_contract.py -q`

Expected: PASS or documented skips only.

- [ ] **Step 4: Commit**

```bash
git add tests
git commit -m "test: add coverage for variable concept index and mcp semantic recall"
```

---

### Task 6: Final Verification & Delivery Notes

**Files:**
- Modify: `docs/superpowers/specs/2026-05-10-pipeline-variable-concept-embedding-design.md` (only if behavior changed)
- Optional Create: `docs/variable-concept-index-ops.md`

- [ ] **Step 1: Verification commands**

Run:
- `uv run python -m pytest tests/test_variable_concept_index.py tests/test_pipeline_variable_concept_index.py tests/test_kn_mcp_variable_concept_search.py -q`
- `uv run python scripts/smj_pipeline/backfill_variable_concept_index.py --all`

Expected:
- tests pass
- backfill prints per-library summary with zero hard failures

- [ ] **Step 2: Manual MCP smoke**

Run:
- start API service
- run MCP probe / direct JSON-RPC call for `graph_variable_concept_search`

Expected:
- valid `ok=true` payload
- `matched_variables` + `papers` populated for known concept query

- [ ] **Step 3: Commit docs/ops adjustments**

```bash
git add docs
git commit -m "docs: document variable concept index operations"
```

---

## Spec Coverage Check

- Pipeline 抽取后 embedding 同步：Task 2
- 复用 Chroma 同体系 + 独立目录：Task 1 + Task 2
- MCP 新 tool、默认 top_k=5：Task 3
- 别名唯一数据源 canonical/alias：Task 1 + Task 3
- 历史回填：Task 4
- 验收与观测：Task 5 + Task 6

## Placeholder Scan

- 无 `TBD/TODO/implement later` 占位。
- 每个任务包含具体文件、命令、预期结果。

## Type/Interface Consistency

- `VariableConceptIndexService` 在 Task 1 定义，并在 Task 2/3/4 复用。
- MCP tool 名称统一为 `graph_variable_concept_search`。
- 默认 `top_k` 全文一致为 `5`。
