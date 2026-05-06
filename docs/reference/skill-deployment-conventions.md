# Skill Deployment Conventions

2026-05-06

本文档记录 Claude Code 和 Codex 的 skill 文件发现机制与部署约定，作为项目 skill 部署逻辑的权威参考。

## 1. Skill 文件结构

两个平台约定一致：每个 skill 是一个目录，`SKILL.md` 为入口文件。

```
<skill-name>/
├── SKILL.md          # 必需，含 YAML frontmatter（name + description）
├── scripts/          # 可选，可执行脚本
├── references/       # 可选，参考文档
├── assets/           # 可选，静态资源
```

## 2. Claude Code Skill 发现路径

来源：https://code.claude.com/docs/en/skills

| 级别 | 路径 | 适用范围 |
|------|------|---------|
| Enterprise | 托管配置 | 组织内所有用户 |
| Personal | `~/.claude/skills/<name>/SKILL.md` | 用户所有项目 |
| **Project** | **`.claude/skills/<name>/SKILL.md`** | 仅当前项目 |
| Plugin | `<plugin>/skills/<name>/SKILL.md` | 插件启用范围 |

- 同名 skill 优先级：Enterprise > Personal > Project
- 支持嵌套目录自动发现（从当前文件所在目录向上查找 `.claude/skills/`）
- `--add-dir` 目录中的 `.claude/skills/` 会被自动加载
- 支持运行时热更新（文件变更在当前会话内生效）
- Skill 内容仅在调用时加载到上下文（惰性加载）

## 3. Codex Skill 发现路径

来源：https://developers.openai.com/codex/skills

| 级别 | 路径 | 适用范围 |
|------|------|---------|
| System | Codex 内置 | 所有用户 |
| Admin | `/etc/codex/skills/<name>/SKILL.md` | 当前机器 |
| User | `~/.agents/skills/<name>/SKILL.md` | 用户所有仓库 |
| **Repo (CWD)** | **`$CWD/.agents/skills/<name>/SKILL.md`** | 当前工作目录 |
| Repo (Parent) | `$CWD/../.agents/skills/<name>/SKILL.md` | 工作目录父级 |
| **Repo (Root)** | **`$REPO_ROOT/.agents/skills/<name>/SKILL.md`** | Git 仓库根目录 |

- 从 CWD 向上遍历到 repo 根目录，扫描每一级的 `.agents/skills/`
- 支持符号链接（跟随目标目录）
- Skill 名称+描述先加载（约 2% 上下文窗口），完整 SKILL.md 仅在调用时加载

## 4. 本项目 Skill 部署策略

### 4.1 模板源

所有 skill 模板存放在 `skills/templates/<skill-name>/SKILL.md`。

当前有两个 skill：

| Skill 名称 | 用途 | 部署目标 |
|-----------|------|---------|
| `answer_library_question` | Chat 问答：RAG 召回 + 证据引用 | **Root workspace** |
| `scholarly-paper-extraction` | 提取论文实体 + 回写笔记 | **Library workspace** |

### 4.2 部署时机

- **Root workspace**：应用启动时（`app.py`）和 Chat 服务首次初始化时（`ChatService._ensure_chat()`）
- **Library workspace**：库 codex 配置首次访问时（`load_or_init_library_codex_config()`）、库创建时（`library_registry.create_library()`）、以及提取管线运行时（`_run_agent_extraction()`，幂等调用）

### 4.3 部署目标

**Root workspace** (`{data_dir}/libraries/workspaces/`) — Chat 对话的 agent cwd：

| Backend | 部署路径 | Skill |
|---------|---------|-------|
| Claude Code | `{root}/.claude/skills/answer_library_question/SKILL.md` | 问答 |
| Codex | `{root}/.agents/skills/answer_library_question/SKILL.md` | 问答 |

**Library workspace** (`{data_dir}/libraries/workspaces/{library_id}/`) — 提取管线的 agent cwd：

| Backend | 部署路径 | Skill |
|---------|---------|-------|
| Claude Code | `{lib}/.claude/skills/scholarly-paper-extraction/SKILL.md` | 提取 |
| Codex | `{lib}/.agents/skills/scholarly-paper-extraction/SKILL.md` | 提取 |

Agent 从 cwd 自动扫描各自的约定目录，因此：
- **不需要** `runtime_overrides` 显式传递 skill 路径
- `bootstrap_workspace_project_skills()` 接受 `skill_names` 参数精确控制部署范围
- 部署时自动清理同名目录下不在允许列表中的旧 skill

### 4.4 cwd 与 Skill 发现关系

```
Chat 对话:
  agent cwd = root workspace (libraries/workspaces/)
  → 自动发现 .claude/skills/answer_library_question/
  → 实现"回答文献库问题"功能

Pipeline 提取:
  agent cwd = library workspace (libraries/workspaces/{lib}/)
  → 自动发现 .claude/skills/scholarly-paper-extraction/
  → 实现"提取论文实体"功能
```

### 4.5 旧路径清理

以下路径为历史错误，已通过 `bootstrap_workspace_project_skills()` 自动清理：

- `{workspace}/.codex_project_skills/` — 无效路径，两边都不识别
- `pipeline_runtime.py` 中 `_run_agent_extraction()` 的调用保留但改为幂等（部署是覆盖式、非累积式）

### 4.6 Skill 过滤机制

`bootstrap_workspace_project_skills(workspace_path, skill_names=None)`：

- `skill_names=None`：部署所有模板 skill（向后兼容）
- `skill_names=["scholarly-paper-extraction"]`：仅部署指定的 skill，并清理不在列表中的旧 skill
- 此机制确保 root workspace 和 library workspace 各自只有所需的 skill

## 5. 相关代码位置

| 文件 | 说明 |
|------|------|
| `skills/templates/scholarly-paper-extraction/SKILL.md` | 提取 Skill 模板源 |
| `skills/templates/answer_library_question/SKILL.md` | 问答 Skill 模板源 |
| `src/kn_graph/services/codex_library_config.py` | Skill 部署与配置管理（含 `skill_names` 过滤） |
| `src/kn_graph/app.py` | 启动时向 root workspace 部署问答 skill |
| `src/kn_graph/services/chat_service.py` | Chat 初始化时部署问答 skill；`bootstrap_library_codex_skills()` |
| `src/kn_graph/services/pipeline_runtime.py` | Pipeline 提取时幂等部署提取 skill |
| `src/kn_graph/services/library_registry.py` | 库创建时部署提取 skill |
| `src/kn_graph/services/agent_runner.py` | Agent runner（通过 cwd 自动发现 skill） |
