# 用户旅程后端测试

## 目标

覆盖 `A/B/C/D/E` 用户旅程的后端可行性：

- `A` 图谱检索 + Chat SSE 终态
- `B` 异步 pipeline 提交/状态/取消/重试
- `C` 文献导入/检索/问答/库列表
- `D` 关键 CLI 链路烟测（筛选、构图、run 激活、run 列表）
- `E` 旅程矩阵完整性与关键路径校验

## 默认必跑（Contract）

```powershell
uv run python -m unittest tests.test_user_journey_contract -v
```

## 可选真实调用（Live）

默认跳过，显式开启：

```powershell
set KN_GRAPH_ENABLE_LIVE_LLM=1
set ZHIPU_API_KEY=your_key
uv run python -m unittest tests.test_user_journey_live -v
```

可选变量：

- `KN_GRAPH_LIVE_ZHIPU_MODEL`（默认 `glm-4.5-flash`）

说明：

- live 用例包含少量真实调用：
  - `POST /chat/provider-test`（Zhipu）
  - `GET /chat/codex/health` + Agent 会话消息链路（Codex 可用时执行，不可用则跳过）
