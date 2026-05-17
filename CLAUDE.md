# CLAUDE.md

## Tool Boundaries And Priority
- Allowed MCP tools: `rag_search`, `graph_variable_neighbors`.
- Use `rag_search` as primary evidence retrieval.
- Use `graph_variable_neighbors` for real KG variable nodes only; concept-only variables may not have neighbors.
- For mechanism/context/conflict judgments, verify with paragraph evidence from `rag_search`.
- If results are truncated or empty, rewrite query and retry before concluding.

## Evidence And Quality Bar
- Every key conclusion must map to paragraph-level evidence.
- If evidence conflicts, state conflict source explicitly instead of forcing a single claim.
- If confidence is limited, state uncertainty reason (insufficient evidence / unstable retrieval / definition mismatch).
- Do not replace evidence with graph-only intuition.

## Incremental Note Maintenance
- Workspace directory map:
  - `corpus/papers/<paper_key>/source/`: source PDFs.
  - `corpus/papers/<paper_key>/derived/mineru/latest/`: parsed markdown/html and assets.
  - `runs/<job_id>/run/extract/`: extraction artifacts (`extract_result.json`, `raw_llm_outputs*.jsonl`).
  - `graph_views.json` / database artifacts: downstream graph/index materials.
- Record only knowledge increment, not abstract restatement.
- If linking to prior literature, include absolute-path markdown links and relation type.
- Relation type examples: same variable, same relation, same mechanism, same context, extension, challenge, conflict, boundary condition.
- For literature-note maintenance, focus on: conflict vs prior work, shared findings, and what is novel in the new paper relative to linked prior papers.
- Keep note text concise and evidence-grounded.
