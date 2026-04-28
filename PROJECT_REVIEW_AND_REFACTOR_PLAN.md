# kn-gragh 项目重构执行计划（可落地版）

> 版本：v2（针对当前 Electron + Python 双进程现状）  
> 日期：2026-04-24  
> 目标：在不打断当前可用功能的前提下，分阶段消除高风险问题并提升可维护性

---

## 0. 适用范围与约束

- 适用仓库：`D:\Code\kn_gragh`
- 当前运行形态：
  - Electron 前端壳 + Web 前端（`frontend/workbench_spa` 等）
  - Python 后端（`serve_graph_api.py` + `serve_async_pipeline_api.py`）
- 约束：
  - 不做“一步到位”大爆炸改造。
  - 每阶段结束必须保持“可启动、可对话、可导入任务”。
  - 禁止要求用户手写 JSON 配置（配置必须有 UI 或明确默认值）。

---

## 1. 风险分级（按修复优先级）

### P0（必须先做）

1. 任务状态机终态可被覆盖（`cancelled` 被后续 `completed/failed` 覆盖）
2. 上传文件名与路径安全边界不清晰（潜在路径穿越/非法字符）
3. CORS 配置与 Electron 场景不一致（可能导致请求被拦截）
4. 生产/开发存储降级策略不透明（意外落到内存存储）

### P1（第二批）

1. 动态加载模块过多（`importlib.util`），可观测性差、IDE 支持差
2. 异步任务与存储的一致性边界不清晰（多进程下行为漂移）
3. 日志与错误模型不统一，排障成本高

### P2（最后做）

1. 前端多技术栈并存，维护成本高
2. API 路由与服务边界松散，演进困难

---

## 2. 执行原则（必须遵守）

1. 小步提交：每个阶段拆成多个可回滚 commit。
2. 先加测试再改实现：至少覆盖回归高发路径。
3. 双入口兼容期：迁移期间保留旧入口，直到新入口完成替换。
4. 明确开关：高风险新行为必须有环境变量开关。
5. 不动用户数据：迁移不得改写已有文献库内容格式。

---

## 3. 分阶段实施计划

## 阶段 A：稳定性与安全热修（1-2 天）

### A1. 状态机单向终态保护

- 目标：`completed/failed/cancelled` 终态不可逆。
- 变更点：
  - `scripts/smj_pipeline/serve_async_pipeline_api.py`
  - `tests/test_async_pipeline_execution.py`
- 验收：
  - 取消后不能再被标记完成。
  - 单测全绿。

> 当前该项已完成，可作为阶段 A 基线。

### A2. 文件上传安全化

- 目标：用户原始文件名可展示，落盘文件名安全规范化。
- 规则：
  - `display_name`：保留原始名（用于 UI）
  - `stored_name`：仅 `[a-zA-Z0-9._-]`，去除路径分隔符与 `..`
  - 强制 `.pdf` 后缀
- 变更点：
  - `serve_async_pipeline_api.py` 上传入口与 job payload
- 验收：
  - 含中文、空格、特殊字符文件名可导入；
  - 落盘路径始终在 `workspace/imports/jobs/<job_id>/input/` 下。

### A3. CORS 与 Electron 兼容

- 目标：不再使用宽泛 `* + credentials` 组合，兼容桌面端。
- 方案：
  - 使用 `CORS_ALLOWED_ORIGINS` 环境变量；
  - 开发默认允许：`http://127.0.0.1:*`、`http://localhost:*`；
  - Electron 场景通过 preload/主进程代理避免 `file://` 直跨域。
- 验收：
  - `npm run start` 后 UI 请求无 CORS 报错；
  - 浏览器调试模式也可访问。

### A4. 存储降级显式化

- 目标：避免“无感降级到内存”。
- 方案：
  - 增加环境变量：`ALLOW_INMEMORY_FALLBACK`（默认 `false`）
  - 当需降级时返回 `degraded=true` 并记录 warning 日志
- 验收：
  - 未配置 DSN 且未允许 fallback 时，启动给出明确错误。

---

## 阶段 B：可维护性改造（2-4 天）

### B1. 动态加载收敛（分批替换）

- 目标：把可静态 import 的模块改为常规 import。
- 策略：
  - 先改无循环依赖模块（utils/service）；
  - 再改路由层；
  - 保留必要的“可选依赖加载点”，但加结构化日志。
- 风险控制：
  - 每替换 2-3 个加载点就跑一次全量后端测试。

### B2. 统一错误码与日志模型

- 目标：前后端错误可追踪、可聚合。
- 方案：
  - 错误结构统一：`{error, code, detail, source, request_id}`
  - 关键链路加 `request_id/job_id/session_id` 透传
  - 引入 JSON 日志格式（保留本地可读模式开关）
- 验收：
  - 任意失败能定位到具体模块与 job/session。

### B3. 任务执行与存储一致性

- 目标：在 inline/celery 两模式下状态一致。
- 方案：
  - 明确任务状态迁移表（文档化）；
  - 禁止跨终态写入；
  - retry 生成新 job，保留 `source_job_id`。
- 验收：
  - 回放测试覆盖：`queued->running->cancelled`、`queued->running->failed->retry`。

---

## 阶段 C：架构收敛（3-5 天）

### C1. 引入统一 app 工厂（兼容期）

- 新增：`scripts/smj_pipeline/webapp.py`
- 做法：
  - 先在新工厂里挂现有路由；
  - 旧入口文件改为薄包装（调用新工厂）；
  - 保持已有 URL 不变，避免前端联调爆炸。
- 验收：
  - `serve_graph_api.py`、`serve_async_pipeline_api.py` 仍可独立启动；
  - 新入口也可一键启动。

### C2. 配置中心化

- 新增：`scripts/smj_pipeline/config.py`
- 原则：
  - 环境变量优先，默认值安全；
  - 不要求用户编辑 JSON；
  - 前端可配置项通过 UI 存储到项目级配置。

---

## 阶段 D：前端整合（可延期，5-10 天）

- 目标：减少并存栈，统一设计系统与状态管理。
- 先决条件：阶段 A/B/C 全部稳定。
- 范围建议：
  1. 先统一组件 Token 与交互规范；
  2. 再迁移页面；
  3. 最后移除旧页面。
- 禁忌：
  - 不要与后端核心改造并行进行。

---

## 4. 测试与验收矩阵

### 自动化测试（每阶段必跑）

```bash
uv run python -m unittest tests.test_async_pipeline_execution tests.test_async_pipeline_api
uv run python -m unittest tests.test_serve_graph_api tests.test_chat_api_endpoints tests.test_literature_service
```

### 手工冒烟（每阶段必做）

1. 启动桌面端：`cd frontend/desktop_shell && npm run start`
2. 新建会话、发送消息、收到回复
3. 批量导入 PDF，观察任务流转
4. 取消任务后确认不会“复活”为完成
5. 关闭前端后后端进程能回收

---

## 5. 回滚与发布策略

- 回滚粒度：按阶段 commit 回滚，不使用 `reset --hard` 破坏现场。
- 发布策略：
  1. `feature` 分支自测
  2. 合并到主干前跑全量测试
  3. 保留 1 个版本开关用于紧急回退（如旧入口开关）

---

## 6. 立即执行清单（下一个迭代）

1. 完成 A2：上传文件名双轨（display/stored）+ 安全校验
2. 完成 A3：CORS 环境化 + Electron 兼容验证
3. 完成 A4：fallback 显式开关 + 降级告警
4. 补充对应单测与 e2e 冒烟记录

---

## 7. 备注

- 原始评审文件存在编码异常，已按“可执行优先”重写。
- 本计划与当前仓库现状对齐，避免一次性重构导致整体不可用。
