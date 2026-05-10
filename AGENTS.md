# KN Graph 项目规约

## 工程约束
- 默认先使用 `using-superpowers`。
- Python 命令统一使用 `uv run`。
- 禁止手工改用户本地 JSON 配置，除非用户明确要求。
- 长任务必须设置超时，后台进程用 `Start-Process`。

## 当前架构（已收口）
- 唯一后端主链路：`src/kn_graph`。
- 统一服务入口：`uv run python -m kn_graph serve --port 8013`。
- Pipeline 运行时在 `src/kn_graph/services/pipeline_runtime.py`。
- PDF 解析固定为：MinerU 精准解析接口（返回 zip）只调用一次。
- 解析后流程固定为：重命名主 Markdown（按首个 H1，Windows 安全）并落到 `derived/mineru/latest`。
- MCP 服务入口：`uv run python src/kn_graph/services/kn_mcp_server.py`。

## 目录
- `src/kn_graph/`：生产代码（唯一业务实现）。
- `scripts/`：已删除。
- `tests/`：测试。
- `docs/`：文档。

## 运行命令
```bash
uv run python -m kn_graph serve --port 8013
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## 禁止项
- 禁止修改 `frontend/`。
- 禁止新增对已删除目录 `scripts/*` 的运行时依赖。
