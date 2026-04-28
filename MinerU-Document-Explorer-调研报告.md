# MinerU Document Explorer 技术调研报告

## 1. 项目概述

**MinerU Document Explorer**（代号 qmd）是由 **OpenDataLab**（MinerU 团队）开发的 **Agent-native 知识引擎**。它是一个面向 AI Agent 的本地文档索引、检索和知识库构建基础设施，通过 **MCP（Model Context Protocol）** 暴露 15 个工具，使大语言模型能够自主地完成以下三类任务：

| 能力组 | 核心作用 | 对应工具数 |
|--------|----------|-----------|
| **Retrieve（检索）** | 在跨文档集合中定位信息 | 4 个 |
| **Deep Read（深度阅读）** | 在单个文档内部导航、定位、精读 | 6 个 |
| **Ingest（知识摄入）** | 从原始文档构建可维护的 Wiki 知识网络 | 5 个 |

项目基于 **MIT 协议**开源，当前版本 v1.0.9，478 stars。其设计哲学是：把"读文档 → 搜信息 → 写知识"的能力直接交给 AI Agent，人类只负责提供文档和提出需求。

---

## 2. 技术架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI Agent (LLM)                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │   决策/推理  │  │  工具调用   │  │  知识合成   │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         │                │                │                         │
│         └────────────────┴────────────────┘                         │
│                          │                                          │
│                    MCP Protocol                                     │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  ┌──────────┐     ┌──────────┐      ┌──────────┐
  │  Core    │     │ Document │      │   Wiki   │
  │  Tools   │     │  Tools   │      │  Tools   │
  │(query/get│     │(doc_toc/ │      │(wiki_ing │
  │/status)  │     │doc_read) │      │est/lint) │
  └────┬─────┘     └────┬─────┘      └────┬─────┘
       │                │                 │
       └────────────────┴─────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
      ┌──────────────┐      ┌────────────────┐
      │  QMD Store   │      │   LLM Models   │
      │              │      │                │
      │  SQLite FTS5 │      │  embedding     │
      │  sqlite-vec  │      │  reranker      │
      │  content-addr│      │  query-expand  │
      │  storage     │      │                │
      └──────┬───────┘      └────────────────┘
             │
      ┌──────┴───────┐
      ▼              ▼
  ┌────────┐   ┌────────────┐
  │Markdown│   │PDF/DOCX/   │
  │(native)│   │PPTX (Python│
  └────────┘   │backends)   │
               └────────────┘
```

### 2.2 核心依赖栈

| 层级 | 技术 | 作用 |
|------|------|------|
| 运行时 | Node.js >= 22 / Bun | TypeScript 执行环境 |
| 数据库 | SQLite + FTS5 + sqlite-vec | 全文检索 + 向量检索 |
| 本地 LLM | node-llama-cpp (GGUF) | embedding / rerank / query expansion |
| 文档解析 | Python 3.10+ (pymupdf / python-docx / python-pptx) | 二进制文档提取 |
| 可选增强 | MinerU Cloud (VLM-based OCR) | 扫描件/复杂排版 PDF 的高精度解析 |

### 2.3 存储层设计

索引文件位于 `~/.cache/qmd/index.sqlite`，核心表结构：

| 表名 | 作用 |
|------|------|
| `content` | 内容寻址存储（hash → 文档文本） |
| `documents` | 虚拟路径 → content hash 映射 |
| `documents_fts` | FTS5 全文索引（porter + unicode61 分词器） |
| `content_vectors` | 文本块的 embedding 向量 |
| `vectors_vec` | sqlite-vec 虚拟表（余弦相似度检索） |
| `llm_cache` | LLM 查询扩展和重排序结果的缓存 |
| `links` | 前向/后向链接追踪 |
| `wiki_log` / `wiki_sources` | Wiki 活动日志与来源溯源 |
| `pages_cache` / `toc_cache` / `slide_cache` | PDF/DOCX/PPTX 的格式专用缓存 |

---

## 3. 核心概念

### 3.1 Collection（集合）

文档被组织为**命名集合**，每个集合是一个带 glob 模式的路径：

```bash
qmd collection add ~/papers --name papers --mask "**/*.{md,pdf,docx,pptx}"
qmd collection add ~/wiki --name mywiki --type wiki   # wiki 类型允许 Agent 写入
```

- **raw 类型**（默认）：只读源文档，Agent 可检索但不可修改
- **wiki 类型**：Agent 可通过 `doc_write` 创建/更新页面，自动记录活动日志

### 3.2 Docid（文档标识符）

每份文档生成一个 6 字符的短 hash（如 `#a1b2c3`），作为稳定标识符。Docid 可用于任何需要文件路径的接口中，不受文件重命名影响。

### 3.3 Address（地址）

地址是连接**导航工具**和**阅读工具**的桥梁：

| 格式 | 含义 | 适用格式 |
|------|------|---------|
| `line:N` / `line:N-M` | 单行或行范围 | Markdown |
| `page:N` | PDF 页码 | PDF |
| `slide:N` | PPTX 幻灯片 | PPTX |
| `section:N` | DOCX 节 | DOCX |
| `heading:标题名` | 标题定位 | 所有格式（通过 TOC） |

地址由 `doc_toc`、`doc_grep`、`doc_query` 返回，必须原样传给 `doc_read`。

### 3.4 Smart Chunking（智能分块）

文档被切分为约 **900 tokens** 的块，重叠率 **15%**。分块边界按语义优先级选择：

| 边界模式 | 优先级分数 | 说明 |
|----------|-----------|------|
| `# Heading`（H1） | 100 | 主要章节边界 |
| `## Heading`（H2） | 90 | 子章节边界 |
| `### Heading`（H3） | 80 | 子子章节 |
| 代码块围栏 | 80 | 代码块边界 |
| `---` / `***` | 60 | 水平分隔线 |
| 空行 | 20 | 段落边界 |
| 列表项 | 5 | 列表项边界 |

算法在目标位置前 200 tokens 的窗口内搜索最高分断点，且代码块内部不会被打断。

---

## 4. 混合搜索流水线详解

### 4.1 完整流水线

```
┌──────────────────┐
│   用户查询输入    │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────┐
│ 强信号检测（BM25 初筛）   │
│ 若 top-1 score ≥ 0.85   │
│ 且与 top-2 差距 ≥ 0.15  │
│ → 跳过扩展，直接用原始查询 │
└────────┬─────────────────┘
         │ (否则)
         ▼
┌──────────────────────────┐
│ 查询扩展（Query Expansion）│
│ 使用微调过的 1.7B 模型     │
│ 生成 lex/vec/hyde 变体    │
│ 去重后最多 N 个扩展查询    │
└────────┬─────────────────┘
         │
    ┌────┴────┬────────┐
    ▼         ▼        ▼
 原始查询   扩展1    扩展N
 (×2 权重)
    │         │        │
    └────┬────┴────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│         并行检索（每个查询）               │
│  ┌────────────┐      ┌────────────────┐  │
│  │ BM25 (FTS5)│      │ Vector Search  │  │
│  │ 关键词匹配  │  +   │ 余弦相似度      │  │
│  └────────────┘      └────────────────┘  │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│      RRF 融合（Reciprocal Rank Fusion）   │
│  score = Σ(weight / (k + rank + 1))      │
│  k = 60, 原始查询结果 ×2 权重             │
│  top-1 加 0.05, top-2~3 加 0.02          │
│  保留 top-40 进入重排序                   │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│       LLM 交叉编码器重排序                 │
│  模型: qwen3-reranker-0.6b                │
│  对每个候选块计算 logprob 置信度           │
└────────────────────┬─────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────┐
│        位置感知混合打分                    │
│  RRF rank 1-3:   blended = 0.75×RRF + 0.25×rerank │
│  RRF rank 4-10:  blended = 0.60×RRF + 0.40×rerank │
│  RRF rank 11+:   blended = 0.40×RRF + 0.60×rerank │
│  目的：前排保护精确匹配，后排信任语义重排序  │
└──────────────────────────────────────────┘
```

### 4.2 评分体系

| 后端 | 原始分数 | 归一化方式 | 范围 |
|------|---------|-----------|------|
| **FTS (BM25)** | SQLite FTS5 BM25 | `abs(score) / (1 + abs(score))` | 0.0 ~ 1.0 |
| **Vector** | 余弦距离 | `1 - distance`（即余弦相似度） | 0.0 ~ 1.0 |
| **Reranker** | LLM logprob 置信度 | 直接使用 | 0.0 ~ 1.0 |

**最终分数解释：**

| 分数区间 | 含义 |
|---------|------|
| 0.8 - 1.0 | 高度相关，通常可直接采用 |
| 0.5 - 0.8 | 中等相关，需人工/Agent 验证 |
| 0.2 - 0.5 | 弱相关，可能包含背景信息 |
| 0.0 - 0.2 | 低相关，通常可忽略 |

### 4.3 查询语法

**简单模式（默认）：**
```json
{ "query": "authentication flow" }
```
系统自动扩展为关键词 + 语义 + 假设文档检索。

**高级模式（精确控制）：**
```json
{
  "searches": [
    { "type": "lex", "query": "\"connection pool\" timeout -redis" },
    { "type": "vec", "query": "why do database connections time out under load" },
    { "type": "hyde", "query": "A 50-100 word passage explaining connection pooling timeouts..." }
  ],
  "intent": "backend infrastructure"
}
```

| 子查询类型 | 方法 | 最佳适用场景 |
|-----------|------|-------------|
| `lex` | BM25 关键词 | 精确术语、名称、`"引号短语"`、`-排除词` |
| `vec` | 向量语义 | 自然语言问题 |
| `hyde` | 假设文档检索 | 写 50-100 字模拟答案段落，用答案检索 |

**特殊前缀（多行查询语法）：**
- `intent: <context>` — 领域上下文，用于消除歧义（不参与搜索，只影响排序）
- `expand: <query>` — 强制使用查询扩展（与 typed lines 不能混用）

---

## 5. 15 个 MCP 工具详述

### 5.1 检索组（Retrieval）— 4 个工具

#### `query` — 混合搜索（主检索工具）

**作用**：全文 + 向量 + 重排序的统一入口。

**参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 与 searches 二选一 | 简单查询字符串，自动扩展 |
| `searches` | array | 与 query 二选一 | 高级：typed sub-queries (lex/vec/hyde) |
| `intent` | string | 否 | 领域上下文，消除歧义 |
| `collections` | string[] | 否 | 限定搜索的集合（OR 匹配） |
| `limit` | number | 否 | 最大返回数，默认 10 |
| `minScore` | number | 否 | 最低相关度 0-1，默认 0 |

**返回**：每条结果包含 `docid`、`file`、`title`、`score`、`snippet`、`line`。

**使用场景**：绝大多数信息查找的第一步。

---

#### `get` — 获取单份文档

**作用**：通过路径或 docid 获取文档全文。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 路径、docid（#abc123）、或 path:line 格式 |
| `fromLine` | number | 起始行号（1-indexed） |
| `maxLines` | number | 最大返回行数 |
| `lineNumbers` | boolean | 输出行号前缀 |

**重要约束**：返回头包含 `Total lines:`。若总行长 > 100，**禁止直接获取全文**，应改用 `doc_toc` + `doc_read`。

**使用场景**：已确定目标为小文件（<100 行）时的全文获取。

---

#### `multi_get` — 批量获取文档

**作用**：通过 glob 模式或逗号分隔列表批量获取多份文档。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `pattern` | string | glob 如 `docs/api*.md`，或逗号分隔如 `a.md, b.md` |
| `maxLines` | number | 每文件最大行数 |
| `maxBytes` | number | 跳过超过此大小的文件（默认 10KB） |

**使用场景**：需要对比多份短文档，或批量收集参考文献。

---

#### `status` — 索引状态

**作用**：返回索引健康度、文档总数、向量索引状态、集合列表。

**使用场景**：工作流开始时的环境侦察；确认哪些集合可用。

---

### 5.2 深度阅读组（Deep Reading）— 6 个工具

#### `doc_toc` — 文档目录

**作用**：获取文档的嵌套目录树，每个节点带 `address`。

**支持格式**：
- Markdown：提取标题层级（# / ## / ###）
- PDF：提取书签/大纲
- DOCX：提取标题样式
- PPTX：提取幻灯片标题

**使用场景**：任何大文件（>100 行、PDF、DOCX、PPTX）的**必读第一步**。获取地图后再决定读哪里。

---

#### `doc_read` — 按地址阅读

**作用**：读取文档中指定地址的内容。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径或 docid |
| `addresses` | string[] | 地址数组，如 `["line:45-120", "page:3"]` |
| `max_tokens` | number | 每段最大 tokens，默认 2000 |

**使用场景**：在 `doc_toc`/`doc_grep`/`doc_query` 获取地址后，执行**精确阅读**。

---

#### `doc_grep` — 文档内关键词搜索

**作用**：在单个文档内进行正则/关键词匹配。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径或 docid |
| `pattern` | string | 正则或关键词（支持 `revenue\|profit` 或） |
| `flags` | string | 正则标志，默认 `"gi"` |

**返回**：匹配结果列表，每条含 `address` 字段。

**使用场景**：已知目标文档，需要快速定位特定术语出现的位置。

---

#### `doc_query` — 文档内语义搜索

**作用**：在单个文档内进行向量语义检索。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径或 docid |
| `query` | string | 自然语言查询 |
| `top_k` | number | 返回 chunk 数，默认 5 |

**前置条件**：必须先运行 `qmd embed` 生成向量索引。

**使用场景**：查找文档中与某概念语义相关但不包含完全匹配关键词的段落。

---

#### `doc_elements` — 提取结构化元素

**作用**：提取表格、图表、公式等结构化内容。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径或 docid |
| `element_types` | string[] | `"table"` / `"figure"` / `"equation"` |
| `query` | string | 按相关性过滤 |
| `addresses` | string[] | 限定提取范围 |

**前置条件**：PDF 高精度提取需配置 MinerU Cloud；DOCX/PPTX 表格支持本地解析。

**使用场景**：从论文或报告中提取数据表格、算法公式。

---

#### `doc_links` — 链接图谱

**作用**：获取文档的前向/后向链接关系。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | string | 文件路径或 docid |
| `direction` | string | `"forward"` / `"backward"` / `"both"` |
| `link_type` | string | `"wikilink"` / `"markdown"` / `"url"` / `"all"` |

**使用场景**：Wiki 知识库中分析页面关联度、发现知识盲区。

---

### 5.3 知识摄入组（Knowledge Ingestion）— 5 个工具

#### `wiki_ingest` — 源文档分析

**作用**：分析源文档并生成 Wiki 处理建议，**不自动生成页面**。

**增量机制**：通过 source hash 判断源文档是否变化。若未变化且非 force，直接返回缓存状态和已衍生页面列表。

**返回内容**：
- 源文档内容（>50k 字符时截断）
- TOC（PDF/DOCX/PPTX）
- 格式元数据（页数/节数/幻灯片数等）
- 相关现有 Wiki 页面
- Wiki 集合结构统计
- 操作建议（如"创建 sources/paper-slug.md"、"审阅 concepts/xxx.md"）

**使用场景**：开始处理一篇新论文/文档时的**第一步**。

---

#### `doc_write` — 写入 Wiki 页面

**作用**：向 wiki 集合写入 Markdown 页面，自动索引并记录日志。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `collection` | string | 目标集合名（必须是 wiki 类型） |
| `path` | string | 相对路径，如 `concepts/cap-theorem.md` |
| `content` | string | 完整 Markdown 内容 |
| `title` | string | 可选：页面标题 |
| `source` | string | **强烈推荐**：源文件路径，用于溯源和过时检测 |

**链接规范**：内容中使用 `[[wikilinks]]` 格式创建交叉引用，如 `[[concepts/dense-retrieval]]`。

**使用场景**：将阅读后的知识沉淀为结构化 Wiki 页面。

---

#### `wiki_lint` — Wiki 健康检查

**作用**：检测 Wiki 知识库中的结构性问题。

**检测项**：
- **孤儿页面**：无任何入链的页面
- **断链**：`[[wikilink]]` 指向不存在的页面
- **缺失页面**：被引用但从未创建的页面
- **过时页面**：源文档更新后未同步更新的 Wiki 页面（通过 `source` 字段 + hash 比对）

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `collection` | string | 限定集合 |
| `stale_days` | number | 过时阈值天数，默认 30 |

**使用场景**：定期维护；知识库构建完成后的质量检查。

---

#### `wiki_log` — 活动日志

**作用**：查看 Wiki 集合的增删改活动历史。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `since` | string | ISO 日期过滤，如 `"2025-01-01"` |
| `operation` | string | 过滤：`ingest` / `update` / `lint` / `query` / `index` |
| `limit` | number | 最大条目数，默认 20 |

**使用场景**：审计知识库变更历史；排查"谁/何时修改了什么"。

---

#### `wiki_index` — 生成索引页

**作用**：根据 Wiki 集合结构自动生成索引页面。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `collection` | string | 目标 Wiki 集合 |
| `write` | boolean | 是否写入 `index.md` 到磁盘 |

**使用场景**：知识库阶段性完成后生成总览目录。

---

## 6. 模型检索信息的标准操作流程（SOP）

### SOP-1：全局信息检索（"找文档"）

**适用场景**：用户提出问题，需要在文档库中定位相关信息。

**步骤**：

1. **环境侦察**
   - 调用 `status` 确认索引状态、可用集合、文档数量
   - 若索引为空或不存在，终止流程并提示用户先建立集合

2. **执行混合搜索**
   - 调用 `query` 传入用户问题的自然语言表述
   - 若问题有歧义，附加 `intent` 参数；若已知目标集合，附加 `collections`
   - 初始 `limit` 设为 10，`minScore` 默认 0

3. **评估结果质量**
   - 遍历返回结果的 `score`：
     - **score >= 0.8**：高置信度，可直接进入阅读阶段
     - **score 0.5~0.8**：中等置信度，可能需要多份文档交叉验证
     - **score 0.2~0.5**：低置信度，考虑简化查询词或改用高级模式
     - **无结果**：尝试更通用的关键词，或确认目标集合是否正确

4. **获取目标文档**
   - 对于小文件（返回头 `Total lines` < 100）：使用 `get` 获取全文
   - 对于大文件/PDF/DOCX/PPTX：使用 `doc_toc` 获取结构，再选择性阅读

5. **交叉验证（可选）**
   - 若涉及事实性问题，使用 `multi_get` 获取 top-3 结果的相关片段
   - 对比多份文档的描述，识别一致性和差异

---

### SOP-2：单文档深度阅读（"读透一篇"）

**适用场景**：用户指定某个文档，需要深入理解或提取特定信息。

**标准流程**：

```
Step 1: 获取文档地图
    └─> doc_toc(file)
        → 返回嵌套目录结构，每个节点带 address

Step 2: 阅读目标章节
    └─> doc_read(file, addresses=[...])
        → 按地址精确读取内容

Step 3a（需要定位关键词）:
    └─> doc_grep(file, pattern="关键词")
        → 返回匹配地址列表
        → 将地址传给 doc_read

Step 3b（需要语义定位）:
    └─> doc_query(file, query="概念描述")
        → 返回语义相关 chunk 地址
        → 将地址传给 doc_read

Step 4（需要结构化数据）:
    └─> doc_elements(file, element_types=["table"])
        → 提取表格/图表/公式

Step 5（构建知识关联）:
    └─> doc_links(file, direction="both")
        → 了解本文档在知识网络中的位置
```

**关键约束**：
- 严禁对 >100 行的文档直接调用 `get`（除非用户明确要求全文）
- `doc_read` 的 `addresses` 参数**必须**来自 `doc_toc`、`doc_grep` 或 `doc_query`
- 阅读时应关注返回的 `Total lines` 和 `Showing lines X-Y` 信息，避免超出上下文窗口

---

### SOP-3：知识库构建（"把文档变成知识网络"）

**适用场景**：用户希望从原始文档构建可维护、可增长的知识体系。

**标准流程**：

```
Phase 1: 源文档分析
    ├─> wiki_ingest(source, wiki_collection)
    │   → 获取内容摘要、TOC、格式元数据
    │   → 获取相关现有页面列表
    │   → 获取操作建议
    │
    ├─> [若内容 >50k 字符或被截断]
    │   → doc_toc(source) → doc_read(source, 关键章节地址)
    │
    └─> 根据建议决定创建哪些页面

Phase 2: 页面撰写
    ├─> doc_write(
    │       collection="wiki",
    │       path="concepts/topic.md",
    │       content="... [[wikilinks]] ...",
    │       source="原始文件路径"    <-- 必须填写，用于溯源
    │   )
    │
    └─> 使用 [[concepts/xxx]] 格式建立交叉引用

Phase 3: 交叉引用扩展
    ├─> query("相关概念") 查找跨文档关联
    ├─> 更新已有页面，添加新链接
    └─> 创建合成性概念页（综合多篇论文的观点）

Phase 4: 质量检查
    ├─> wiki_lint(collection="wiki", stale_days=30)
    │   → 修复孤儿页面、断链、过时内容
    ├─> wiki_log(since="...") 审查活动历史
    └─> wiki_index(collection="wiki", write=true) 生成总览索引
```

**Wiki 页面模板**：

```markdown
# 页面标题

**Source:** [[sources/原始文件名]]

## 核心要点
- ...

## 方法/实现
...

## 实验结果
...

## 关联知识
- 相关概念：[[concepts/概念A]]
- 扩展阅读：[[concepts/概念B]]
- 对比方法：[[papers/论文C]]
```

---

### SOP-4：研究文献综述（多文档综合分析）

**适用场景**：用户要求对一组论文/文档进行综述、比较或趋势分析。

**标准流程**：

```
Step 1: 广度检索
    └─> query("综述主题")
        → 获取 top-N 相关文档列表

Step 2: 单篇精读（循环）
    对每篇候选文档：
    ├─> doc_toc(file) → 理解结构
    ├─> doc_read(file, ["摘要/引言地址", "方法地址", "结果地址"])
    ├─> doc_elements(file, ["table"]) → 提取关键数据表格
    └─> doc_write(wiki, path="papers/xxx.md", ...)

Step 3: 维度对比
    ├─> 用 query 分别检索各个子维度：
    │   query("dense retrieval methods")
    │   query("multi-hop QA benchmarks")
    │   query("reranking strategies")
    ├─> doc_read 各维度 top 结果
    └─> 在 concept 页面中综合对比

Step 4: 综述撰写
    └─> doc_write(wiki, path="survey.md", content="结构化综述")

Step 5: 质量闭环
    └─> wiki_lint → wiki_index → 最终审阅
```

---

## 7. 决策树：何时使用何种工具

```
START
  │
  ├─ "看看有哪些文档/索引状态" → status
  │
  ├─ "找关于X的资料" → query
  │     ├─ 结果 score >= 0.8 且文档小 → get
  │     ├─ 结果 score >= 0.8 且文档大 → doc_toc → doc_read
  │     └─ 结果 score < 0.5 → 简化 query 重试，或改用高级 searches 模式
  │
  ├─ "获取这个具体文件" → get (path 或 #docid)
  │     ⚠ 若返回 Total lines > 100 → 改 doc_toc + doc_read
  │
  ├─ "批量获取几个文件" → multi_get (glob 或逗号分隔)
  │
  ├─ "这篇论文/报告讲了什么" → doc_toc → doc_read(关键章节)
  │     ├─ 要找特定术语 → doc_grep → doc_read
  │     ├─ 要找某类概念 → doc_query → doc_read
  │     └─ 要提取数据表 → doc_elements
  │
  ├─ "把这些资料整理成知识库" → wiki_ingest → doc_read → doc_write
  │     └─ 完成后 → wiki_lint + wiki_index
  │
  ├─ "知识库健康检查" → wiki_lint
  │     ├─ 有孤儿页面 → 添加 [[wikilinks]] 入链
  │     ├─ 有断链 → 修复链接或创建缺失页面
  │     └─ 有过时页面 → doc_read 源文档 → doc_write 更新
  │
  └─ "知识库改了什么" → wiki_log
```

---

## 8. 本地模型与资源

### 8.1 自动下载的 GGUF 模型

| 模型 | 用途 | 大小 | 来源 |
|------|------|------|------|
| `embeddinggemma-300M-Q8_0` | 文本 embedding | ~300MB | HuggingFace |
| `qwen3-reranker-0.6b-q8_0` | 交叉编码器重排序 | ~640MB | HuggingFace |
| `qmd-query-expansion-1.7B-q4_k_m` | 查询扩展（团队微调） | ~1.1GB | HuggingFace |

模型缓存在 `~/.cache/qmd/models/`，首次运行 `qmd embed` 或 `qmd query` 时自动下载。

### 8.2 可选自定义 Embedding 模型

通过环境变量切换：
```bash
export QMD_EMBED_MODEL="hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf"
qmd embed -f   # 切换后必须强制重新嵌入
```

### 8.3 内存与性能特征

| 场景 | 延迟 | 说明 |
|------|------|------|
| `qmd search`（BM25） | <100ms | 纯 SQLite FTS5，无需 LLM 模型 |
| `qmd query` 首调 | 5-15s | 模型加载到显存/内存 |
| `qmd query` 后续 | 1-3s | 模型常驻内存 |
| MCP stdio 模式 | 每次调用都加载 | 适合 Claude Desktop 等管理生命周期的客户端 |
| MCP HTTP daemon | 一次加载，持续服务 | 推荐用于 Cursor/VS Code 等多客户端场景 |

**推荐配置**：生产环境始终使用 `qmd mcp --http --daemon`，保持模型常驻。

---

## 9. 与其他方案的对比

| 维度 | MinerU Doc Explorer | LlamaIndex | Obsidian | NotebookLM |
|------|--------------------|-----------|----------|-----------|
| **完全本地运行** | 是 | 部分（需 LLM API） | 是 | 否（云端） |
| **Agent 集成** | **15 个 MCP 工具** | 插件/SDK | 无原生支持 | 无 |
| **单文档深度阅读** | 是（TOC + 地址导航） | 否 | 否 | 是 |
| **Wiki 知识编译** | 是（LLM Wiki 模式） | 否 | 手动 | 否 |
| **支持格式** | MD, PDF, DOCX, PPTX | 多种 | 仅 MD | PDF, URL |
| **搜索管道** | BM25 + 向量 + 重排序 | 可配置 | 基础搜索 | 专有黑盒 |
| **零配置搜索** | `qmd search` 即开即用 | 需编排 | 需插件 | N/A |
| **开源协议** | MIT | MIT | 部分开源 | 闭源 |

---

## 10. 关键约束与最佳实践

### 10.1 路径规范
- 始终使用 **collection-relative 路径**：`papers/survey.pdf`、`wiki/concepts/rag.md`
- 绝对路径（如 `/Users/xxx/file.md`）不被接受
- 可用 `qmd://collection/path` 格式显式指定

### 10.2 大文件处理
- **禁止**对超过 100 行的文件直接调用 `get`
- 标准流程：`doc_toc` 获取结构 → `doc_read` 按地址读取
- PDF/DOCX/PPTX 等二进制文件**必须**走 `doc_toc` 流程

### 10.3 地址桥接
- `doc_toc`、`doc_grep`、`doc_query` 返回的 address 字符串**必须原样传递**给 `doc_read`
- 不要手动构造地址（如猜测行号），地址格式可能因文档类型而异

### 10.4 MCP vs CLI 选择
- **Agent 工作流优先使用 MCP**：模型常驻内存，延迟低
- **CLI 仅用于**：一次性操作、脚本化任务、没有 MCP 客户端的环境
- `qmd search`（纯 BM25）是 CLI 中最快的命令，无需模型加载

### 10.5 Wiki 写作规范
- **必须填写 `source` 参数**：这是溯源和过时检测的基础
- **使用 `[[wikilinks]]` 而非 Markdown 标准链接**：只有 wikilink 会被 `wiki_lint` 和 `doc_links` 追踪
- **分层组织页面**：建议 `sources/` 放原文摘要，`concepts/` 放概念综合，`papers/` 放单篇分析

### 10.6 查询策略
- **简单查询优先**：大多数情况下 `{ "query": "自然语言问题" }` 效果最好
- **高级模式用于**：需要精确控制（如排除词、短语匹配、假设文档）或简单模式召回不足时
- **善用 `intent`**：当查询词有歧义时（如 "performance"），用 intent 指明领域（如 "web page load times"）

---

## 11. 典型部署方式

### 方式一：npm 全局安装（推荐）

```bash
npm install -g mineru-document-explorer
pip install pymupdf python-docx python-pptx

# 建立索引
qmd collection add ~/Documents --name mydocs --mask "**/*.{md,pdf,docx,pptx}"
qmd embed

# 启动 MCP HTTP 服务
qmd mcp --http --daemon
```

### 方式二：源码部署

```bash
git clone https://github.com/opendatalab/MinerU-Document-Explorer.git
cd MinerU-Document-Explorer
bun install && bun link

# 开发模式运行
bun src/cli/qmd.ts --index mydocs mcp --http
```

### 客户端配置示例

**Cursor**（HTTP 模式，推荐）：
```json
{
  "mcpServers": {
    "qmd": {
      "url": "http://localhost:8181/mcp"
    }
  }
}
```

**Claude Desktop / Claude Code**（stdio 模式）：
```json
{
  "mcpServers": {
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
```

---

## 12. 局限性说明

1. **二进制文档依赖 Python**：PDF/DOCX/PPTX 的解析需要 Python 3.10+ 和对应包，纯 Node 环境无法处理
2. **向量检索需预先生成**：`qmd embed` 是一次性操作，新增文档后需重新运行
3. **MinerU Cloud 为付费选项**：高精度 PDF OCR 和表格提取需要 API key
4. **Embedding 模型不兼容**：切换 embedding 模型后必须 `qmd embed -f` 全量重建向量索引
5. **doc_elements 对 PDF 支持有限**：本地模式下 PDF 的表格/图表提取质量取决于 PyMuPDF，不如 MinerU Cloud
6. **macOS 需要额外安装 sqlite**：`brew install sqlite` 以支持扩展加载

---

## 13. 总结

MinerU Document Explorer 是当前为数不多的**专门为 AI Agent 设计**的本地知识基础设施。其核心优势在于：

1. **完整的 Agent 工具链**：15 个 MCP 工具覆盖"检索 → 精读 → 建库"全链路
2. **高质量的混合搜索**：BM25 + 向量 + 查询扩展 + LLM 重排序，四阶段融合
3. **单文档深度阅读能力**：地址系统让 Agent 可以像人类一样"翻目录、跳章节"
4. **可溯源的 Wiki 模式**：Karpathy 的 LLM Wiki 思想的工程化实现
5. **完全本地运行**：数据不出境，适合敏感文档和企业内网

对于需要让 AI Agent 自主处理大量本地文档（论文、报告、设计文档、法律合同等）的场景，这是一个值得重点评估的基础设施方案。
