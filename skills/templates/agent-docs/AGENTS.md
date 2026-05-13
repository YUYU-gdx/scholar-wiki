# CLAUDE.md

## 工具边界与优先级
- 允许使用的 MCP 工具：`rag_search`、`graph_variable_neighbors`。
- 优先使用 `rag_search` 作为主证据检索工具。
- `graph_variable_neighbors` 仅用于变量级对齐与邻域核查。
- 对机制、情境、冲突等判断，必须用 `rag_search` 返回的段落证据进行验证。
- 如果结果被截断或为空，先改写查询并重试，再给出结论。

## 证据与质量标准
- 每条关键结论都必须对应到段落级证据。
- 若证据冲突，必须明确说明冲突来源，不能强行合并为单一结论。
- 若置信度有限，必须说明不确定性原因（证据不足、召回不稳定、定义不匹配等）。
- 不要用纯图谱直觉替代文本证据。

## 增量笔记维护
- Workspace 目录约定：
  - `corpus/papers/<paper_key>/source/`：源 PDF。
  - `corpus/papers/<paper_key>/derived/mineru/latest/`：解析后的 markdown/html 与资源文件。
  - `runs/<job_id>/run/extract/`：抽取产物（`extract_result.json`、`raw_llm_outputs*.jsonl`）。
  - `graph_views.json` / 数据库产物：下游图谱与索引材料。
- 仅记录“知识增量”，不要做抽象复述。
- 若链接到既有文献，需包含绝对路径 markdown 链接与关系类型。
- 关系类型示例：同变量、同关系、同机制、同情境、扩展、挑战、冲突、边界条件。
- 文献笔记维护重点：与既有工作是否冲突、共同发现、以及新论文相对既有文献的新意。
- 笔记保持简洁，并以证据为中心。
