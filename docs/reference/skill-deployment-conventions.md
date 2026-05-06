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

### 4.2 部署时机

**workspace / library 初始化时一次性部署**，而非每次 pipeline job 运行时复制。

触发场景：
- `bootstrap_library_codex_skills()` 调用（现有 API）
- 或在 `ensure_data_dirs()` / 库创建流程中自动触发

### 4.3 部署目标

对每个 library workspace，同时部署到两个约定的路径：

| Backend | 部署路径 | 说明 |
|---------|---------|------|
| Claude Code | `{workspace}/.claude/skills/{name}/SKILL.md` | Claude Code 从 cwd 自动发现 |
| Codex | `{workspace}/.agents/skills/{name}/SKILL.md` | Codex 从 cwd 向上遍历发现 |

两个 backend 都从 cwd (= workspace root) 自动扫描各自的约定目录，因此：
- **不需要** `runtime_overrides` 显式传递 skill 路径
- **不需要** pipeline runtime 每次复制
- agent 启动后自动发现

### 4.4 旧路径清理

以下路径为历史错误，应清理：

- `{workspace}/.codex_project_skills/` — 无效路径，两边都不识别
- `pipeline_runtime.py` 中 `_run_agent_extraction()` 的逐次复制逻辑 — 应删除

## 5. 相关代码位置

| 文件 | 说明 |
|------|------|
| `skills/templates/scholarly-paper-extraction/SKILL.md` | Skill 模板源 |
| `src/kn_graph/services/codex_library_config.py` | Skill 部署与配置管理模块 |
| `src/kn_graph/services/pipeline_runtime.py` | Pipeline 运行时（含错误的逐次复制逻辑） |
| `src/kn_graph/services/chat_service.py` | `bootstrap_library_codex_skills()` |
| `src/kn_graph/services/agent_runner.py` | Agent runner（ClaudeCodeRunner 未消费 project_skills） |
