# Agent Extraction Mode Design

2026-05-05

为论文信息提取节点新增 agent 模式，通过 agent（Codex / Claude Code / Gemini CLI）的 skills 机制完成提取 + 消歧 + 笔记三步工作流，替代单次 LLM 调用的 fast 模式。

## 1. 现状

- `extraction_mode` 字段已存在于 `global_settings.json` → `categories.pipeline.extraction_mode`（值为 `fast` 或 `agent`）
- 前端 Settings UI 已有 fast/agent 下拉切换，但 agent 选项标注"暂只预留接口，后续扩展"
- Settings 后端 (`settings_service.py`) 已读写 `extraction_mode`，但 pipeline runtime 未消费
- Pipeline runtime 只走 fast 路径：`_run_extract_entities()` → `run_extraction_mvp()` → 单次 LLM `complete()` 调用

## 2. 目标

当 `extraction_mode == "agent"` 时，pipeline 不调用 `run_extraction_mvp()`，而是启动 agent（Codex CLI / Claude Code / Gemini CLI），让 agent 自主完成三步工作流并产出结构化抽取结果。

Agent 后端和 LLM 配置独立于 chat，通过 Settings → `pipeline_agent` 分类单独管理。

## 3. Skill 设计

### 3.1 Skill 名称

`scholarly-paper-extraction`（英文名，让 agent 明确这是学术论文的实体提取任务）

### 3.2 Skill 文件位置

`skills/templates/scholarly-paper-extraction/SKILL.md`

由 `codex_library_config.py` 的 `bootstrap_workspace_project_skills()` 模式复制到 workspace → `.codex_project_skills/`。

### 3.3 三步工作流

**Step 1 — 初版实体提取**

Agent 自行读取给定路径的论文 markdown 文件（MinerU 解析产物），按照 extraction schema 提取：
- `variable_definitions`: 变量定义列表
- `direct_effects`: 直接效应列表
- `moderations`: 调节效应列表
- `interactions`: 交互效应列表
- `paper_domains`: 研究领域
- `extractability_status`: 可提取性
- `paper_type`: 论文类型

初版结构化结果写入 `extract/entities_v1.json`。

**Step 2 — 变量消歧与别名填充**

1. 遍历 Step 1 所有变量的 `definition`（概念描述，非变量名本身）
2. 用每个变量的定义/概念描述调 `rag_search` 在文献库中检索可能相同的概念
3. 自主判断是否需要 `weaviate_fetch_object` 查看源论文原文做对比
4. 确认同一概念后，填充变量的 `aliases` 字段（用于后续图合并）
5. 写入 `extract/entities_v2.json`

**Step 3 — 阅读笔记回写**

基于 LLM wiki 理念，将笔记直接写入源 markdown 文件（非独立笔记文件）。

笔记触发条件：

| 类型 | 说明 | 标签 |
|------|------|------|
| 核心洞见 | 论文对供应链研究的独特贡献，非摘要复述 | `#insight` |
| 矛盾发现 | 新提取结论与已有文献冲突 | `#contradiction` |
| 方法论要点 | 样本/测量/设计可取或可质疑之处 | `#method` |
| 跨论文关联 | 变量/概念可能与其他论文存在关联 | `#connection` |
| 待探索问题 | 论文引发但未解答、值得追踪的问题 | `#question` |

不该记：摘要复述、琐碎细节、原始数据罗列。

查找上下文的方法：
1. 用变量定义/概念描述调 `rag_search` 找回相关段落
2. 用 `graph_search` 找回图谱中相关变量和效应
3. 用 `weaviate_fetch_object` 查询源文献原文做对比
4. 用 grep 搜索 workspace 内已有笔记，避免重复

笔记格式（写在源 markdown 文件末尾）：

```
> 📝 [2026-05-05] #insight
>
> SC integration (SCI) 在此文中被定义为三级构念（supplier/customer/internal），
> 这与 [Flynn et al. 2010](corpus/papers/flynn2010/paper.md) 的二维定义不同。
> 该差异可能导致合并时的维度不匹配。
>
> 相关变量: `SCI_supplier`, `SCI_customer`
> 待确认: 是否需要将 Flynn 2010 的定义也升级为三维？
```

### 3.4 最终输出

Agent 将三步结果汇总，写入 `extract/extract_result.json`，格式与现有 `extract_records_with_raw` 返回的 bundle 一致：

```json
{
  "paper_domains": ["supply_chain"],
  "extractability_status": "yes",
  "paper_type": "empirical",
  "extractability_reason": "...",
  "extractability_evidence_section": "...",
  "variable_definitions": [{...}],
  "direct_effects": [{...}],
  "moderations": [{...}],
  "interactions": [{...}],
  "aliases": {"var_id": ["alias1", "alias2"]}
}
```

下游 `_run_finalize()` 无需任何改动。

### 3.5 Workspace CLAUDE.md / AGENTS.md 补充

Agent 需要理解文献库目录结构。Skill 中需描述：

```
# 文献库目录结构

{library_workspace}/
├── corpus/papers/        # 论文源文件
│   └── {paper_key}/
│       ├── paper.md      # MinerU 解析的 markdown（agent 读取对象）
│       ├── paper_meta.json
│       ├── paper.pdf      # 原始 PDF
│       └── v30.md         # 源文件的其他版本
├── graph_views.json       # 知识图谱视图（只读）
└── kn_gragh.db            # SQLite 知识库
```

Skill 需说明：agent 只能读取 `paper.md` 并向其中追加笔记，不能修改其他文件。

## 4. Settings 设计

### 4.1 新增 `pipeline_agent` 分类

在 `global_settings.json` → `categories` 下新增 `pipeline_agent`，结构完全参照 chat 的 `agent_settings`：

```json
{
  "categories": {
    "pipeline": {
      "extraction_mode": "fast",
      ...
    },
    "pipeline_agent": {
      "backend": "codex",
      "provider": "deepseek",
      "model": "",
      "api_key": "",
      "base_url": "",
      "endpoint_url": ""
    },
    "translation": {...},
    "agent_settings": {...}
  }
}
```

### 4.2 Settings 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `backend` | string | `codex` | Agent 后端：`codex` / `claude_code` / `gemini_cli` |
| `provider` | string | `deepseek` | LLM provider ID |
| `model` | string | `""` | 模型名（空则用 provider 默认） |
| `api_key` | string | `""` | API key |
| `base_url` | string | `""` | API base URL |
| `endpoint_url` | string | `""` | Chat completions endpoint |

### 4.3 Config 流（参照 chat 模式）

```
Settings UI → PUT /settings/pipeline_agent
  → SettingsService._save_pipeline_agent_category()
  → global_settings.json → categories.pipeline_agent
  → Settings.load_global_settings() 读取
  → pipeline_runtime._inject_pipeline_settings() 注入 options
  → _run_extract_entities():
      extraction_mode == "fast" → run_extraction_mvp()（现有）
      extraction_mode == "agent" → _run_agent_extraction()（新增）
```

### 4.4 Settings model 变更

`config.py` 的 `Settings` 新增字段：

```python
pipeline_agent_backend: str = "codex"
pipeline_agent_provider: str = "deepseek"
pipeline_agent_model: str = ""
pipeline_agent_api_key: str = ""
pipeline_agent_base_url: str = ""
pipeline_agent_endpoint_url: str = ""
pipeline_extraction_mode: str = "fast"
```

`load_global_settings()` 中从 `categories.pipeline` 读取 `extraction_mode`，从 `categories.pipeline_agent` 读取 agent 配置。

### 4.5 SettingsService 变更

`settings_service.py` 新增：

- `_get_pipeline_agent_category()` — 返回 pipeline_agent 配置（参照 `_get_translation_category` 模式）
- `_save_pipeline_agent_category()` — 保存 pipeline_agent 配置（参照 `_save_translation_category` 模式）
- `get_all()` 中增加 `pipeline_agent` 到返回的 settings
- `get_schema()` 中增加 `pipeline_agent` 分类
- `update_category()` 中增加 `pipeline_agent` 分支

## 5. Pipeline Runtime 变更

### 5.1 `pipeline_runtime.py`

`_run_extract_entities()` 增加模式判断：

```python
def _run_extract_entities(job_id, parse_meta, run_dir, store, options):
    mode = str(options.get("extraction_mode", "fast")).strip().lower()
    if mode == "agent":
        return _run_agent_extraction(job_id, parse_meta, run_dir, store, options)
    else:
        # 现有 fast 逻辑
        ...
```

### 5.2 `_run_agent_extraction()` 实现

完全参照 `chat_legacy._run_agent()` 的调用模式：

1. **读取 agent 配置** — 从 options 获取 `pipeline_agent_backend`、`pipeline_agent_provider` 等
2. **写入 agent config 文件** — 参照 `chat_service._write_agent_config()` 模式，将 provider/model/api_key/base_url 写入 `{data_dir}/chat/{backend}_config.json`。必须先写再 build，因为 `AgentRunnerFactory._read_agent_config()` 在 `build()` 时从该文件读取
3. **构建 AgentRunnerFactory** — `AgentRunnerFactory(codex_config_path={data_dir}/chat/codex_runner_config.json)`
4. **注入 Skill** — 参照 `codex_library_config.bootstrap_workspace_project_skills()`，将 `skills/templates/scholarly-paper-extraction/` 复制到 workspace 的 `.codex_project_skills/`
5. **构建 runtime_overrides** — 不依赖 library_codex_config，直接构造：
   ```python
   runtime_overrides = {
       "mcp_servers": [
           {"name": "kn_graph_tools", "command": "uv",
            "args": ["run", "python", str(mcp_server_script)], "env": {}}
       ],
       "project_skills": [
           {"name": "scholarly-paper-extraction", "path": str(skill_target_path)}
       ]
   }
   ```
6. **调用 runner.run_turn()** — 签名完全参照 chat_legacy:1270：
   ```python
   result = runner.run_turn(
       query=extraction_prompt,
       workdir=library_workspace,
       library_id=library_id,
       thread_id="",
       runtime_overrides=runtime_overrides,
       on_event=None,
   )
   ```
7. **读取结果** — `extract_dir / "extract_result.json"`，反序列化为 extract_result；若文件不存在或 JSON 非法，抛 `RuntimeError("agent_extraction:missing_or_invalid_result")`。从 extract_result 构造 bundle 对象（与 `_process_class_a_record` 中 `extract_records_with_raw` 返回值结构一致），返回给调用方

### 5.3 extraction prompt

```python
extraction_prompt = (
    f"请按照 scholarly-paper-extraction skill 处理以下论文：\n"
    f"论文 markdown 路径: {html_path}\n"
    f"library_id: {library_id}\n"
    f"输出目录: {extract_dir}\n"
    f"请完成三步流程后将最终结构化结果写入 {extract_dir}/extract_result.json"
)
```

Agent 不接收论文内容，只收路径。

### 5.4 `_inject_pipeline_settings()` 扩展

在现有 `pipeline_fast_*` 注入基础上，增加 `pipeline_agent_*` 和 `extraction_mode` 的注入：

```python
# extraction_mode
if not str(out.get("extraction_mode", "") or "").strip():
    val = str(getattr(settings, "pipeline_extraction_mode", "fast")).strip()
    if val:
        out["extraction_mode"] = val

# pipeline_agent_backend
if not str(out.get("pipeline_agent_backend", "") or "").strip():
    val = str(getattr(settings, "pipeline_agent_backend", "codex")).strip()
    if val:
        out["pipeline_agent_backend"] = val

# ... 同上 pattern 注入 provider/model/api_key/base_url/endpoint_url
```

## 6. 输出兼容性

Agent 和 fast 模式产出的 `extract_result` 结构完全一致（见 3.4），确保 `_run_finalize()` 和下游导入逻辑无需改动。

Agent 模式下 `_process_class_a_record` 不被调用，`bundle` 直接从 `extract_result.json` 反序列化得到，直接走 `replace_paper_bundle` 入库。

## 7. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `skills/templates/scholarly-paper-extraction/SKILL.md` | 新增 | Skill 定义 |
| `src/kn_graph/config.py` | 修改 | 新增 pipeline_agent_* 和 extraction_mode 字段 |
| `src/kn_graph/services/settings_service.py` | 修改 | 新增 pipeline_agent 分类读写 |
| `src/kn_graph/services/pipeline_runtime.py` | 修改 | 新增 agent 分支 + config 注入 |
| `src/kn_graph/services/chat_legacy.py` | 无需修改 | runtime_overrides 在 pipeline_runtime 内直接构造 |
| `scholarai-workbench/src/components/SettingsView.tsx` | 修改 | 移除 agent 模式的"暂只预留接口"提示，显示 agent 配置表单 |

## 8. 测试策略

### Stage 1：仅抽取节点测试

- 准备一篇已解析的论文 markdown 和对应的 library workspace
- 启动 agent backend（codex/claude_code），确保其可用
- 在 settings 中配置 pipeline_agent，设置 extraction_mode=agent
- 调用 `_run_agent_extraction()` 隔离测试
- 验证：`extract_result.json` 产出、格式符合 schema、笔记回写到源 markdown
- 覆盖：Claude Code 和 Codex 两个 backend

### Stage 2：完整 Pipeline 后端测试

- 通过 pipeline API 提交一个 PDF 任务
- 设置 `extraction_mode=agent`
- 等待完整流程：parse_pdf → extract_entities (agent) → finalize
- 验证：任务状态=completed、graph_views.json 更新、SQLite 入库正确
- 验证 agent 失败时的错误处理（agent_unavailable、timeout 等）

### Stage 3：Playwright E2E 测试

- 在 `tests/e2e/run_settings_tests.py` 中加入 pipeline_agent 分类测试
- 切换到 agent 模式 → 配置 agent backend/provider → 保存 → 刷新验证持久化
- 提交 pipeline 任务 → 等待完成 → 在 graph 页面验证新节点出现
- 在 reader 页面验证笔记可见

## 9. 风险与限制

- Agent 调用耗时长（多轮 tool call），单篇论文可能 30-180 秒，远超 fast 模式（5-15 秒）
- Agent 输出格式依赖 prompt/skill 约束，可能在边界情况下产出不合法 JSON，需要加解析容错
- Claude Code backend 需要 `ANTHROPIC_API_KEY` 或兼容环境
- Gemini CLI 的 skill 机制与 Claude Code/Codex 不同，需要验证适用性
- 如果 agent process 中途崩溃，pipeline job 会被标记为 failed，需要重试机制
