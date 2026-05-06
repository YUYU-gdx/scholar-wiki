# 模块化单体重构计划（文献问答主场景）

## Summary
- 目标形态：在不砍功能、不降复杂度前提下，把当前系统重构为“模块化单体 + 单一 React Shell + Postgres 主存 + 向量旁路”的产品架构。
- 交付策略：新建 `git worktree` 全量迁移开发，保留旧入口与旧 API 全兼容，采用“新壳接管、分模块切流、可回退”的双轨发布。
- 优先级：`文献问答 -> 文章导入解析与实体抽取 -> 3D 知识图谱 -> 阅读器 -> 笔记 -> 多分页工作台能力深化`。

## Key Changes
1. 架构重组（后端）
- 将当前 `serve_graph_api.py` 的混合职责拆为 6 个 domain module：`chat`、`literature`、`graph`、`pipeline`、`reader`、`notes`，外层只保留 API Gateway（路由聚合、鉴权、SSE 网关、静态资源分发）。
- 保持单进程部署，但强制分层：`api -> application -> domain -> infra`，禁止跨域直接读写底层存储。
- 统一任务编排：异步流水线（PDF 解析、实体抽取）纳入 `pipeline` domain，状态机标准化为 `queued/running/completed/failed/cancelled`，事件流统一 schema。

2. 数据底座重构（Postgres 主存）
- Postgres 作为唯一业务真相源，建立核心聚合：
  - `library`（文献库）
  - `paper`（文章元数据与解析状态）
  - `entity/relation`（抽取结构化结果）
  - `chat_session/message/citation`
  - `note/vault/page/block/link/tag`
  - `reader_state`（阅读进度、高亮、批注、收藏）
  - `workspace/layout/pane/tab`
- 向量检索改为旁路索引（ChromaDB 嵌入式实现），不承载主业务字段，仅承载 embedding 与召回辅助键。
- 现有 JSON 产物（graph views、中间产物）保留为缓存/导出层，不再作为业务主存。

3. 前端重构（单一 React Shell）
- 用统一壳层替代“graph 静态页 + chat 独立页”并存模式，建立固定工作台信息架构：
  - 左侧：文献库/图谱/笔记/会话导航
  - 中央：主内容区（问答、阅读器、图谱、编辑器）
  - 右侧：上下文面板（实体、引用、证据、关系、属性）
  - 多分页：Tab + Pane 可拆分布局（保存为 workspace layout）
- 功能模块化为前端子域：
  - `qa`：检索问答与引用追踪
  - `import`：导入、解析、抽取任务管理
  - `graph3d`：3D 关系探索与证据回链
  - `reader`：类似 Zotero 的文献阅读与管理
  - `notes`：类似 Obsidian 的 markdown 笔记与双链
- 定义跨模块统一对象引用协议：`paper_id`、`node_id`、`note_id`、`citation_id`，支持互跳与反向追踪。

4. 能力闭环设计（按业务链路）
- 主链路闭环：`导入文章 -> 解析与实体抽取 -> 图谱更新 -> 文献问答引用 -> 阅读定位 -> 笔记沉淀 -> 回写图谱关联`。
- 问答优先支持“证据可追溯”：每条回答必须可展开到 `paper + section/snippet + relation`。
- 阅读器与笔记不是附属页，而是问答与图谱的“证据与知识沉淀层”：问答可一键生成阅读任务或笔记草稿，笔记可反向挂到实体节点。

5. 兼容层与迁移
- 保持旧 API 全兼容：现有 `/graph/*`、`/chat/*`、`/literature/*`、`/v1/jobs/*` 全部保留；新 API 走 `/api/v2/*`。
- 在 Gateway 层提供协议适配器，把旧响应映射到新 domain 输出，保证前端灰度期稳定。
- 前端兼容：保留旧入口 URL，逐步 302/内部路由切换到新 Shell。
- 数据迁移分三步：`schema 建立 -> 历史数据回填 -> 双写校验 -> 切主读`。

6. 工程组织与分支策略
- 新建 `worktree` 进行全量迁移，独立分支开发，主仓仅接收阶段性可回滚合并。
- 里程碑按“可运行切片”提交，每个里程碑必须包含：代码、迁移脚本、回归测试、回滚说明。
- 强制契约测试：旧 API contract 不允许无评审变更。

## Implementation Phases
1. Phase 0：基线冻结与设计落版（1 周）
- 冻结现有 API 契约与关键用户旅程。
- 产出 v2 架构蓝图、领域模型、事件模型、迁移清单。

2. Phase 1：后端骨架与网关落地（1-2 周）
- 建立模块化单体目录与依赖边界。
- 接入统一 API 网关与路由注册机制。
- 将 chat/literature/graph/pipeline 先做“壳迁移”（逻辑不变，位置重组）。

3. Phase 2：数据层统一（2 周）
- 建立 Postgres 新 schema 与仓储层。
- 完成 chat + literature + pipeline 关键表迁移与双写。
- 打通向量旁路索引同步任务。

4. Phase 3：主场景闭环重构（2 周）
- 重构文献问答链路为统一检索编排器（关键词/向量/图谱融合）。
- 引用对象标准化，确保回答可回溯到文章证据。

5. Phase 4：导入解析与实体抽取重构（2 周）
- 统一导入任务模型与任务中心 UI。
- 解析/抽取状态标准化 + SSE 事件统一 + 错误码体系化。

6. Phase 5：3D 图谱与问答联动重构（2 周）
- 图谱模块迁入新 Shell。
- 节点/边详情与问答上下文双向联动（from_node/from_relation/from_paper）。

7. Phase 6：阅读器与笔记系统接入（3 周）
- 阅读器（文献列表、标签、收藏、阅读进度、高亮批注）上线。
- Obsidian 风格笔记（Markdown、双链、反向链接、图谱引用）上线。
- 建立“引用到笔记”“笔记到实体”的双向跳转。

8. Phase 7：多分页工作台与体验收敛（1-2 周）
- 完成左右分栏 + 多 tab + 可保存布局。
- 完成跨模块拖拽打开（文章/节点/笔记拖入新 pane）。

9. Phase 8：切流与收口（1 周）
- 开启 v2 默认入口，旧入口保留兜底。
- 完成性能压测、稳定性压测、迁移验收与回滚演练。

## Public APIs / Interfaces
- 保留兼容：
  - `GET /graph/*`
  - `POST|GET /chat/*`
  - `POST|GET /literature/*`
  - `POST|GET /v1/jobs/*`
- 新增统一 v2：
  - `GET /api/v2/workspace/layout`
  - `POST /api/v2/import/jobs`
  - `GET /api/v2/reader/papers/{paper_id}`
  - `POST /api/v2/notes`
  - `POST /api/v2/qa/answer`
  - `GET /api/v2/graph/neighborhood`
- 统一事件流协议（SSE）：
  - `started | progress | citation | tool_call | completed | failed | cancelled`

## Test Plan
- 契约测试：
  - 旧 API 全量 contract snapshot（必须持续通过）。
  - v2 API 新增 contract + schema 校验。
- 集成测试：
  - `导入 -> 抽取 -> 图谱 -> 问答 -> 阅读 -> 笔记` 全链路。
  - SSE 断线重连、任务取消、失败恢复。
- 前端 E2E：
  - 多分页布局保存/恢复。
  - 图谱点选跳问答、问答引用跳阅读、阅读摘录进笔记、笔记反链回图谱。
- 性能与稳定性：
  - 图谱大数据集加载、问答并发、pipeline 队列积压、长连接稳定性。
- 数据迁移验收：
  - 历史数据行数校验、抽样语义一致性、双写一致性、切换回滚演练。

## Assumptions
- 采用策略：`模块化单体 + Postgres 主存 + 单一 React Shell + 全兼容迁移 + 问答优先`。
- 接受“新建 worktree 全量迁移”的实施方式，并以分阶段切流控制风险。
- 向量能力默认继续复用现有能力并抽象旁路接口，不阻塞主链路重构。
