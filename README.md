# Scholar Wiki

学术知识图谱平台 — 将论文 PDF 自动解析、提取、构建为可交互的知识图谱，并支持 AI 对话问答。

## 功能概览

| 模块 | 功能 |
|------|------|
| **Library** | 文献库管理，支持多库并行、论文浏览、PDF/Markdown 阅读 |
| **Pipeline** | 一键导入 PDF，自动解析 → 提取 → 入库 → 构建图谱 |
| **Graph** | 3D 力导向知识图谱，展示变量间因果关系、调节效应、交互效应 |
| **Chat** | AI Agent 对话，可调用文献检索和图谱查询工具回答学术问题 |
| **Reader** | 多标签论文阅读器，支持 PDF 标注、Markdown 编辑、WikiLink 跳转、翻译 |
| **Settings** | 全局配置：LLM 供应商、Embedding 模型、Agent 后端、MinerU API |

---

## 知识管理 Pipeline

当你导入一篇新论文时，系统会经历以下流程：

```
PDF 上传
  │
  ▼
┌──────────────────────────────────────────────────────┐
│ Stage 1: MinerU 解析                                  │
│   PDF → MinerU API → Markdown + HTML                  │
│   提取全文、表格、公式，生成结构化文档                     │
└──────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────┐
│ Stage 2: 实体提取（Fast / Agent 两种模式）               │
│                                                      │
│  Fast 模式:                                           │
│    1. classify_document — 判断论文是否可提取             │
│    2. locate_evidence  — 定位关键证据段落               │
│    3. LLM extract      — 提取结构化记录                │
│    4. validate         — 校验关系合理性                 │
│                                                      │
│  Agent 模式:                                          │
│    1. 在论文工作区部署 scholarly-paper-extraction 技能   │
│    2. Claude Code / Codex 自主阅读全文并提取             │
│    3. 输出符合 schema 的结构化 JSON                     │
│                                                      │
│  提取内容:                                            │
│    • 变量定义（名称、概念、测量方式、别名）                │
│    • 直接效应（A → B，含效应方向、证据、验证状态）         │
│    • 调节效应（M 调节 A → B 的关系）                     │
│    • 交互效应（多变量 → 结果）                           │
│    • 论文元数据（标题、作者、期刊、DOI）                  │
└──────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────┐
│ Stage 3: 入库 & 索引                                   │
│   • 论文内容写入 ChromaDB（句子/段落级向量索引）           │
│   • 提取的结构化数据写入 SQLite（kn_gragh.db）           │
│   • 构建 graph_views.json（前端使用的图谱快照）           │
│   • 同步变量概念索引                                    │
└──────────────────────────────────────────────────────┘
```

完成后，论文即可在 Library、Graph、Chat 中使用。

---

## Chat Agent 工具

Agent 模式下，AI 可以自主调用以下工具来回答你的问题：

### MCP 工具（kn_graph_tools）

| 工具 | 功能 | 使用场景 |
|------|------|---------|
| `rag_search` | 在 ChromaDB 中混合检索（向量 + 关键词），搜索句子/段落级证据 | "这篇论文里关于供应链弹性的证据有哪些？" |
| `graph_variable_neighbors` | 查找变量的上下游因果邻居（前因/后果） | "Adoption propensity 的前因变量是什么？" |
| `graph_variable_concept_search` | 跨论文匹配变量的概念定义 | "哪些论文定义了供应链中断这个概念？" |

### SDK 内置工具

Agent 还拥有文件系统读写、代码执行、网页搜索等能力，可以：
- 阅读论文原文（Markdown/HTML）
- 搜索学术数据库
- 撰写文献综述

### 工具调用追踪

每次对话中，Agent 的工具调用过程完全透明——你可以看到它调用了哪个工具、传入了什么参数、得到了什么结果。

---

## 知识图谱亮点

### 关系类型

图谱不只是"节点+边"，而是包含细粒度的学术关系：

| 关系类型 | 含义 | 示例 |
|---------|------|------|
| **Direct Effect** (直接效应) | A 对 B 有因果影响 | "供应链多元化 → 企业韧性" |
| **Moderation** (调节效应) | M 调节 A → B 的关系强度 | "环境不确定性 调节 供应链多元化 → 企业韧性" |
| **Interaction** (交互效应) | 多个变量共同影响结果 | "研发投入 × 市场导向 → 创新绩效" |

### 效应方向

每条直接效应都有明确的效应方向：

- **Positive** (正向) — A 增加，B 增加
- **Negative** (负向) — A 增加，B 减少
- **Nonlinear** (非线性) — 倒 U 型、U 型等
- **Unclear** (不明确) — 效应方向未明确或存在争议

### 用法

1. **全局搜索** — 顶部搜索框，输入变量名或关键词，跨库搜索
2. **语义搜索** — Graph 视图中，输入自然语言描述，找到语义相近的变量
3. **邻居展开** — 点击节点查看其上下游因果邻居
4. **多库合并** — 侧边栏勾选多个文献库，图谱自动合并，跨库发现关联
5. **聚焦节点** — 点击变量名或从搜索结果跳转，相机自动飞向目标节点
6. **关系详情** — 点击边查看效应方向、证据原文、验证状态、来源论文

### 数据溯源

每个节点和边都关联到来源论文。点击可跳转到 Reader 中查看原文证据段落。

---

## 技术架构

```
Scholar Wiki (Electron Desktop App)
  │
  ├── 前端: React 19 + TypeScript + Vite + Tailwind CSS
  │   ├── 3D 图谱: Three.js + 3d-force-graph
  │   ├── PDF 渲染: react-pdf
  │   └── Markdown: CodeMirror 6 + markdown-it + KaTeX
  │
  └── 后端: Python 3.12 + FastAPI
      ├── PDF 解析: MinerU API
      ├── 向量搜索: ChromaDB (sentence/paragraph embedding)
      ├── 关键词搜索: SQLite FTS5 + BM25
      ├── 结构化存储: SQLite (论文元数据、变量、效应)
      └── Agent: Claude Agent SDK / Codex CLI / Gemini CLI
```

## 快速开始

```bash
# 启动后端
uv run python -m kn_graph serve --port 8013

# 启动前端 (另一个终端)
cd scholarai-workbench
npm run dev:electron
```

首次使用需在 Settings 页面配置 LLM API Key。
