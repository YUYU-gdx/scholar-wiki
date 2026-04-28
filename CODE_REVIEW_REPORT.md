# kn-gragh 全仓库代码审查报告

> 日期：2026-04-28
> 范围：全仓库（Python 后端 / 前端 / 测试 / 配置 / 文档）
> 方法：4 个并行 Agent 分别审查后端、前端、测试、管线代码，汇总合并

---

## 项目概览

知识图谱 + 研究论文处理管线，包含：

- **Python 后端**：FastAPI 异步管线 + 纯 Python HTTP 图谱服务
- **存储**：PostgreSQL + Redis + Weaviate + Neo4j + SQLite
- **前端**：Electron 桌面壳 + React SPA + Vanilla JS 嵌入式组件 + 3D 图谱
- **LLM 管线**：多 Provider 抽取 + 文献 RAG 问答 + Codex Agent 会话

---

## 统计

| 严重级别 | 数量 | 关键主题 |
|----------|------|----------|
| **P0 严重** | 13 | RCE、命令注入、SQL/GraphQL 注入、XSS、Neo4j 运行时错误、数据损坏、凭据泄露 |
| **P1 高危** | 16 | 无鉴权、无限速、内存泄漏、竞态条件、上传校验不足、测试无效化 |
| **P2 中危** | 18 | SSRF、代码重复、静默异常吞没、事务安全、测试质量问题 |
| **P3 低危** | 15 | 性能、资源泄露、边界情况、可访问性、死代码 |

**总计 62 项发现**。

---

## P0 — 严重问题（需立即修复）

### 1. RCE — Codex Install 端点可执行任意命令

**文件**：`scripts/smj_pipeline/serve_graph_api.py:1229-1251`

攻击者可通过无鉴权的 `/chat/codex/config` POST 设置 `install_command` 为任意 shell 命令，再调用 `/chat/codex/install` 触发执行。**完整远程代码执行向量**。

**建议**：移除此端点，或至少要求鉴权并将命令限制为预定义白名单。

---

### 2. 命令注入 — MINERU_CMD 环境变量模板注入

**文件**：`scripts/smj_pipeline/literature/service.py:651-656, 977-983`

`MINERU_CMD` 模板中的 `{input}` / `{output}` 占位符使用裸字符串替换，未加 shell 引号。含空格的文件路径会导致命令解析错误；若攻击者修改 `.env`，可注入任意命令。

**建议**：使用固定命令 + 参数列表，不要使用用户可配置的模板字符串。

---

### 3. Neo4j — 关系到关系的边（运行时必定失败）

**文件**：`scripts/smj_pipeline/storage/neo4j_repo.py:34, 61, 87`

```python
# 行 34, 61
MERGE (p)-[:MENTIONS_EFFECT]->(r)
# 行 87
MERGE (p)-[:MENTIONS_INTERACTION]->(r)
```

`r` 是 `DIRECT_EFFECT` / `MODERATES` / `INTERACTS` 关系变量。**Neo4j 属性图模型不允许关系作为关系的端点**。这些 Cypher 语句在运行时会抛出错误——**Neo4j 投影路径从未正确运行过**。

**建议**：将效应物化为中间节点（如 `(:DirectEffect)`），或将 `(p)` 直接连接到参与节点 `(s)` 和 `(t)`。

---

### 4. PostgreSQL — `RETURNING` 无行时静默数据损坏

**文件**：`scripts/smj_pipeline/storage/postgres_repo.py:267, 338`

```python
fetched = cursor.fetchone()
moderation_id = int(fetched[0]) if fetched else 0  # 默认 0！
```

`INSERT ... RETURNING id` 在异常情况下返回 `None` 时，ID 被默认为 `0`。后续所有子行以 `moderation_id=0` 插入，违反引用完整性。孤儿清理查询随后会 DELETE 这些合法数据。

**建议**：`fetched` 为 `None` 时抛出明确错误，不使用默认值 `0`。

---

### 5. LLM Provider — OpenAICompatible 客户端重试无退避

**文件**：`scripts/smj_pipeline/llm/provider_registry.py:154-170`

```python
for attempt in range(1, self.max_retries + 1):
    try:
        response = requests.post(...)
    except requests.RequestException as exc:
        # 无 time.sleep()！立即重试！
```

对比 `zhipu_client.py:61` 和 `nvidia_client.py:68` 均有 `time.sleep(1.5 * attempt)` 退避。此客户端在失败时立即重试，可能加剧速率限制和服务端负载。

**建议**：添加 `time.sleep(min(1.5 * attempt, 10))`。

---

### 6. SQL 注入 — ORDER BY 子句

**文件**：`scripts/smj_pipeline/serve_async_pipeline_api.py:315, 496`

`sort` 参数虽在 API 层做了校验，但 `list_jobs` 方法内部直接拼接 SQL。若从其他代码路径调用且未预校验 `sort` 值，即构成注入。

**建议**：在 store 方法内部使用白名单映射，永远不要将用户控制的字符串拼入 SQL。

---

### 7. GraphQL 注入 — Weaviate 查询拼接

**文件**：`scripts/smj_pipeline/literature/service.py:408-434`

BM25 搜索的 GraphQL 查询通过手动字符串格式化构建。转义仅处理 `\` 和 `"`，未处理闭合大括号、注释符 `#` 等 GraphQL 元字符。

**建议**：使用 GraphQL 客户端库的参数化查询。

---

### 8. 凭据泄露 — PostgreSQL DSN 通过命令行传递

**文件**：`scripts/smj_pipeline/app_launcher.py:120-138`

用户输入的 DSN（含用户名/密码）直接作为命令行参数传递。完整连接字符串对系统所有用户可见（`ps`、任务管理器）。

**建议**：通过环境变量或限制权限的临时文件传递 DSN。

---

### 9. CORS 配置安全漏洞

**文件**：`scripts/smj_pipeline/serve_async_pipeline_api.py:995-996`

```python
CORSMiddleware, allow_origins=["*"],
```

**建议**：改为 `CORS_ALLOWED_ORIGINS` 环境变量白名单。

---

### 10. XSS — Chat Embed 引文按钮

**文件**：`frontend/chat_embed/app.js:329-333`

```javascript
btn.innerHTML =
  '<div class="citation-item-title">[' + (idx+1) + '] ' + title + '</div>' + ...
```

整个 1300 行文件中**唯一使用 `innerHTML` 的位置**（其余全部正确使用 `textContent`）。API 返回的 `title`/`snippet` 未转义。存储型 XSS 向量。

**建议**：改用 `createElement` + `textContent`。

---

### 11. XSS — dangerouslySetInnerHTML CDN 故障时降级不安全

**文件**：`frontend/workbench_spa/app.js:172-189`

DOMPurify 从 CDN 加载失败时，回退到仅替换 `\n` 为 `<br/>`——不处理 `<`、`>`、`&`。原始 HTML 标签直接通过。

**建议**：将 DOMPurify 打包为本地依赖。

---

### 12. 文件上传路径安全 + 缺少魔数校验

**文件**：`scripts/smj_pipeline/serve_async_pipeline_api.py`

仅按扩展名校验 PDF，未做：路径穿越防护、PDF 魔数 `%PDF` 校验、上传大小限制、display_name / stored_name 分离。

**建议**：校验 PDF 魔术字节、限制 100MB、stored_name 仅允许 `[a-zA-Z0-9._-]`。

---

### 13. 存储静默降级到内存（数据丢失风险）

**文件**：`scripts/smj_pipeline/serve_graph_api.py:1154-1161`

任何加载异常都导致静默降级到 `_InMemoryWorkspaceLayoutStore`——**工作区布局在重启后丢失**。前端未对 `degraded=true` 做告警。

**建议**：`ALLOW_INMEMORY_FALLBACK` 环境变量默认 `false`；前端检测 `degraded` 字段并弹窗。

---

## P1 — 高优先级问题

### 14. 所有 API 端点无鉴权

**文件**：`serve_graph_api.py`（全局）、`serve_async_pipeline_api.py`（全局）

任何有网络访问权限的人都可以：创建/删除 chat 会话、执行 Codex agent run、导入文件、修改配置、触发 LLM 调用、取消/重试管线。

**建议**：至少为写操作（POST/DELETE）添加 API key 中间件。

---

### 15. 无上传大小限制

**文件**：`serve_async_pipeline_api.py:612-624`

攻击者可上传超大文件耗尽磁盘空间。`_save_upload` 循环无总大小上限。

**建议**：在上传处理早期添加 100MB 上限。

---

### 16. 内存泄漏 — EventHub 无限增长

**文件**：`scripts/smj_pipeline/chat_service.py:519-555`

```python
self._states: dict[str, _EventState] = {}  # 永不清理
```

长期运行的服务中事件状态无限累积直至 OOM。

**建议**：对已完成/失败的消息添加 TTL 驱逐（如完成后 1 小时）。

---

### 17. 竞态条件 — 消息 "running" 崩溃后永久卡住

**文件**：`scripts/smj_pipeline/chat_service.py:760-765, 781-834`

Assistant 消息在 daemon 线程中运行。服务崩溃时线程被直接杀死，消息永久留在 "running" 状态。无启动恢复扫描。

**建议**：添加启动恢复扫描；使用非 daemon 线程 + 关闭信号。

---

### 18. 会话撤销窗口重启后丢失

**文件**：`scripts/smj_pipeline/chat_service.py:625, 662-688`

```python
self._restore_deadline_by_session: dict[str, float] = {}  # 纯内存
```

软删除的 5 秒撤销窗口完全依赖内存。服务重启后，已删除会话**永久不可恢复**。

**建议**：将 `deleted_at` 持久化到数据库。

---

### 19. Daemon 线程数据丢失

**文件**：`serve_async_pipeline_api.py:862-863`, `chat_service.py:760-765`

daemon 线程在进程退出时被直接终止。管线和 chat assistant 无清理机会。"running" job 永远不会标记为 failed。

**建议**：非 daemon 线程 + 关闭信号 + job 超时 + 启动恢复扫描。

---

### 20. Chat 消息提交硬编码忽略 provider/model

**文件**：`serve_graph_api.py:1380-1382`

```python
mode = "agent"; provider = "codex"; model = "codex-local"
# 请求体中的 provider 和 model 字段被完全忽略
```

---

### 21. Agent Runner — model 硬编码降级

**文件**：`scripts/smj_pipeline/agent_runner.py:121-122`

```python
if model_name == "gpt-5.4": model_name = "gpt-5.2"
```

静默改变用户模型选择，无日志。

---

### 22. 35+ 处 `importlib.util` 动态加载

**影响（20+ 个文件）**：`serve_graph_api.py`(10)、`serve_async_pipeline_api.py`(6)、`chat_service.py`(3)、`literature/service.py`(2)、其余 15+ 个脚本各 1-2 处。

IDE 无补全/跳转支持；运行时才暴露错误；测试中模块被双次加载导致状态共享 bug。

**建议**：提取通用 `_load_module(name, path)` → 逐步替换为常规 import。

---

### 23. 前端无 CSRF 保护

所有前端应用（`chat_embed`, `chat_spa`, `workbench_spa`）的 fetch 调用不带 CSRF token。

---

### 24. 前端错误被静默吞没（10+ 处）

```javascript
.catch(function () {})  // 无日志、无用户提示
catch { setSessions([]) }  // 错误对象被丢弃
```

---

### 25. SSE 流轮询浪费

`chat_embed/app.js:1042-1072` — 轮询每 1.5s 运行，即使在 EventSource 流正常工作时也不停止。

---

### 26. 测试 — 最终状态断言非确定性

**文件**：`tests/test_async_pipeline_api.py:90`

```python
self.assertIn(result_resp.status_code, (200, 404))
```

测试名声称应返回 404，但因异步调度时间不确定，同时接受 200。**回归时不会报错**。

---

### 27. 测试 — `time.sleep()` 等待服务器就绪（4 处）

`test_chat_api_endpoints.py:188`, `test_serve_graph_api.py:161`, `_e2e_helpers.py:356,398`

固定 sleep 替代就绪轮询。慢机器上产生连接拒绝错误。

---

### 28. 测试 — SSE 测试用 `time.sleep(0.9)`（易抖动）

`test_async_pipeline_api.py:156-213` — 至少 2.7s 墙钟时间，CI 过载时抖动的确定性高。

---

### 29. 测试 — `test_storage_postgres_repo.py` 实际测试 SQLite

用 `sqlite3.connect(":memory:")` 测试 `PostgresRepo`。PostgreSQL 特有语法（`ON CONFLICT DO UPDATE`、`JSONB` 运算符）完全未被测试。

---

## P2 — 中优先级问题

### 30. SSRF — Preflight 探针使用请求 Host 头

**文件**：`serve_graph_api.py:1651-1655`

```python
host = self.headers.get("Host", "")
base_url = f"{scheme}://{host}"  # 攻击者可控制
```

**建议**：使用固定 `http://127.0.0.1:{port}`。

---

### 31. extractor.py — `context_variables` 绕过类型校验

**文件**：`scripts/smj_pipeline/extraction/extractor.py:86-93`

`context_variables` 被跳过 dict-item 校验 (`continue`)，而后被 `_coerce_string_list` 强制转字符串列表。若 LLM 返回对象列表则产生垃圾数据。

---

### 32. extractor.py — 裸 `except Exception` 捕获（3 处）

**文件**：`extraction/extractor.py:332, 359, 369`

捕获 `KeyboardInterrupt` 和 `SystemExit`，阻止正常关闭。

---

### 33. `zhipu_client.py` — 漏掉 HTTP 408 重试

行 60 的重试码列表缺少 `408`（Request Timeout）。`nvidia_client.py` 正确包含。

---

### 34. LLM 客户端重试逻辑重复

`zhipu_client.py:50-73` ↔ `nvidia_client.py:56-80` — 近乎相同。`_extract_content_text` 函数完全一致。

---

### 35. PostgresChatStore 事务不完整

**文件**：`chat_service.py:371-390`

`create_message` 插入消息与更新 `chat_sessions.updated_at` 不在同一事务中。

---

### 36. Weaviate Schema 迁移静默吞异常

**文件**：`literature/service.py:329-333`

向已有 class 添加属性时的异常被静默忽略。

---

### 37. `schema.sql` 缺少 chat 表

SQLite schema 缺少 `chat_sessions`、`chat_messages`、`chat_events`。若应用使用 SQLite 回退则运行时报错。

---

### 38. 数据库 schema 缺少外键约束

所有表无 FOREIGN KEY。引用完整性仅靠应用代码维护——任何应用 bug 可产生孤儿行。

---

### 39. 数据库 schema 缺少连接列索引

`paper_domains(paper_id)`、`variable_definitions(paper_id)`、`moderation_targets(moderation_id)` 等均无索引。

---

### 40. neo4j_repo.py — N+1 查询反模式

每行 effect 触发一次独立 `session.run()`（网络往返）。应使用 `UNWIND` 批量写入。

---

### 41. postgres_repo.py — 330 行单体方法

`replace_paper_bundle` 包含 paper upsert、domain、variable definitions、operationalizations、effects、moderations、interactions 全部逻辑。

---

### 42. Windows 路径穿越保护不够健壮

`serve_graph_api.py` — 使用 `str(path).startswith(str(root))`。Windows 大小写不敏感文件系统下可能被绕过。

**建议**：使用 `path.resolve().is_relative_to(root.resolve())`。

---

### 43. MinerU 子进程无超时

`literature/service.py:656-658` — `subprocess.run` 无 `timeout`。若子进程挂起则线程永久阻塞。

---

### 44. `skills/` 在 `.gitignore` 但已被 Git 追踪

`.gitignore:36` 排除 `skills/`，但 `skills/answer_library_question/` 和 `skills/templates/` 已在仓库中。

---

### 45. 测试 — `test_classify_base_dataset_abc.py` 运行 subprocess 而非调用函数

需要 `uv` 在 PATH、无法调试、无法度量覆盖率、无法与其他测试并行。

---

### 46. 测试 — `test_literature_service.py` 直接猴子补丁而非 `unittest.mock`

```python
_MOD.subprocess.run = _fake_run   # 全局状态
service._run_mineru_to_dir = _fake_mineru  # 方法重命名时测试静默通过
```

---

### 47. 测试 — MCP Server 零覆盖

`scripts/smj_pipeline/kn_mcp_server.py` 无任何测试。这是 Codex Agent 的关键集成点。

---

## P3 — 低优先级 / 改善建议

### 48. 后端

- Paper 查找 O(n) 回退（`serve_graph_api.py:750-757`）— 应构建二级索引
- SQLite 连接未显式关闭（`serve_async_pipeline_api.py`）
- Windows 保留文件名未检查（`literature/service.py:127-133` — `CON`, `NUL` 等）
- MCP Server JSON 截断破坏结构（`kn_mcp_server.py:94-96`）
- `requests.Response` 流式上下文管理器异常时连接泄露风险
- YAML 解析器未缓存（`extractor.py`）
- `_LegacyTextClientAdapter` 忽略 `timeout_seconds` 参数
- OpenAICompatible 假流式：先获取完整响应再分块 yield
- `_safe_windows_filename` 未检查保留名
- `postgres_repo.py` 方言检测脆弱（按 `type(conn).__module__` 判断）
- SQL 按分号分割脆弱（字符串字面量含分号时错误）
- Dead code：`schemas.py` 中 `DirectEffectSchema` 未被使用
- Dead code：`extractor.py` 中 `_complete_with_messages` 无意义包装

### 49. 前端

- `jfetch`/`jsonFetch` 在 4 个应用中各自复制
- 多个前端技术栈并存（6 个应用，3 种构建方式）
- `chat_spa` 无 Error Boundary — 任何错误导致白屏
- `chat_spa` 每条 delta 重渲染整个消息列表
- EventSource 重连逻辑：线性退避误标为"指数"，4xx 错误也重试
- Electron Windows 进程终止过于激进（`taskkill /F /T` 无优雅关闭）
- GoldenLayout `stateChanged` 防抖 1200ms 过长
- Dead code：`setChatStage()` 函数体为空；空 toolbar `<div>`
- CSS 文件跨应用无共享设计 token
- `chat_embed/index.html` CSS 路径依赖服务端 URL 重映射
- `chat_spa/index.html` 仅兼容 Vite dev server
- 3D 图谱无键盘导航；按钮缺 `aria-label`
- `window.__graphPointerX/Y` 全局变量污染

### 50. 测试

- `test_chat_service_paragraph_policy.py` — 相同 lambda 复制粘贴 7 次
- `test_graph_chat_playwright_e2e.py` — 删除测试在按钮不存在时静默通过
- `test_async_pipeline_api.py` — `time.sleep(0.05)` 替代就绪检查
- 两个独立的 `FakeChatService` 实现（`_e2e_helpers.py` ↔ `test_chat_api_endpoints.py`）
- `test_chat_api_endpoints.py` API 测试断言中文 UI 文本
- `test_merge_smj_manifests.py` — 仅 2 个简单测试
- `test_evaluation_metrics.py` — 无溢出/负值测试
- `test_no_pypdf_usage.py` — 每次运行扫描全仓库文件
- 无并发请求测试
- 无性能/负载测试

---

## 亮点（做得好的方面）

1. **Electron 进程管理**（`desktop_shell/main.js`）— 双后端生命周期、优雅关闭、端口自动发现
2. **异步管线状态机**（`serve_async_pipeline_api.py`）— 终态保护、cancel/retry 机制
3. **LLM Provider 配置化**（`config/llm_providers.json` + `llm/provider_registry.py`）— 注册/热替换合理
4. **详尽的 API 文档**（`docs/api.md`）— 9 个端点完整规约，含 SSE 事件类型
5. **纯 Python HTTP 服务器**— 避免 uvicorn 依赖，适合桌面嵌入
6. **前端整体 XSS 防护意识强**— `chat_embed/app.js` 除 1 处外全部使用 `textContent`
7. **重构执行计划务实**（`PROJECT_REVIEW_AND_REFACTOR_PLAN.md`）— 分阶段、可回滚、有验收条件
8. **抽取管线验证细致**— `parse_extraction_response` 对必需键、项类型、枚举值校验完整

---

## 建议修复顺序

### 即刻（安全热修）
1. **移除或锁定 `/chat/codex/install` 端点** — RCE
2. **修复 MINERU_CMD 命令注入** — 不要模板拼接命令
3. **SQL ORDER BY 白名单映射** — 防御纵深
4. **修复 Neo4j 关系到关系边** — 运行时必定崩溃
5. **修复 PostgreSQL RETURNING 空行默认 0** — 静默数据损坏

### 本周
6. CORS 白名单化
7. 添加 API key 鉴权（至少 POST/DELETE）
8. 文件上传安全化 — 魔数 + 大小限制 + 路径安全
9. 修复前端 XSS（引文按钮 + DOMPurify 本地化）
10. 存储降级显式化 + 前端告警
11. LLM OpenAICompatible 客户端添加重试退避

### 本月
12. EventHub 内存泄漏 — TTL 驱逐
13. 消息/任务状态启动恢复扫描
14. 前端错误不再静默吞没
15. 测试 `time.sleep` 替换为就绪轮询
16. 测试 SQLite/PostgreSQL 混淆修复
17. 收敛动态加载 — 提取通用函数

### 本季度
18. 拆分 `serve_graph_api.py` 和 `postgres_repo.py` 单体
19. 引入统一 app 工厂
20. GraphQL 参数化查询（Weaviate）
21. 数据库添加外键约束和索引
22. Neo4j 批量写入（UNWIND）
23. 前端技术栈评估与整合
24. MCP Server 测试覆盖
