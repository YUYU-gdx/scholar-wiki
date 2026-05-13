# Graph API 规约

## 服务入口
- 统一入口：`uv run python -m kn_graph serve --port 8013`
- 默认地址：`http://127.0.0.1:8013`

## 核心接口
- `GET /graph/overview`
- `GET /graph/full`
- `GET /graph/search`
- `GET /graph/neighborhood`
- `GET /paper/{id}`
- `GET /paper/{id}/files`
- `GET /variable/{id}`

## 约定
- 返回 `application/json; charset=utf-8`（静态文件除外）。
- 404 语义化错误码：`paper_not_found` / `node_not_found`。
- `/paper/{id}/files` 优先展示：PDF > Markdown > HTML。
- `/graph/full` 返回的 `paper_map` 论文元数据（title、doi、authors、source_pdf_path 等）**仅来源于 SQLite `papers` 表**，不依赖 graph_views.json。
