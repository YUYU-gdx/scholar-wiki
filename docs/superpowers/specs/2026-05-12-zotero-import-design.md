# Zotero 本地库导入功能设计

## 概述

在"文献导入"页面增加"从 Zotero 导入"功能。扫描本地 Zotero 数据库，展示文献列表供用户选择性导入。导入走现有管道系统，元数据以 Zotero 为准，模型提取仅在 Zotero 字段为空时兜底。

## Zotero 数据存储背景

### 数据目录定位

- 默认路径（Windows）：`%USERPROFILE%\Zotero`
- 自定义路径存储在 `%APPDATA%\Zotero\Zotero\Profiles\<profile>.default\prefs.js`：
  - `extensions.zotero.useDataDir` — 是否启用自定义目录
  - `extensions.zotero.dataDir` — 自定义数据目录的绝对路径
- 前端提供输入框，默认尝试自动检测，支持用户手动指定

### SQLite 核心表

| 表 | 用途 |
|----|------|
| `items` | 一切实体：文献条目、笔记、附件、标注 |
| `itemData` + `itemDataValues` + `fields` | EAV 模型存储条目字段值 |
| `creators` + `itemCreators` | 作者（名、姓、角色、排序） |
| `itemNotes` | 笔记内容（`parentItemID` 指向父文献） |
| `itemAttachments` | PDF 附件（`path` 字段，`parentItemID` 指向父文献） |
| `itemAnnotations` | PDF 标注（高亮/下划线/便利贴/手绘，含已提取文字） |
| `collections` + `collectionItems` | 文件夹/集合（多对多） |
| `tags` + `itemTags` | 标签（多对多） |

### PDF 附件路径解析

| path 前缀 | 含义 | 完整路径 |
|-----------|------|---------|
| `storage:filename.pdf` | Zotero 内部存储 | `<dataDir>/storage/<itemKey>/filename.pdf` |
| `attachments:rel/path` | 链接文件（相对） | `<baseDir>/rel/path`（baseDir 在 settings 表） |
| 绝对路径 | 链接文件（绝对） | 直接使用 |

### PDF 标注格式

- `position`：JSON `{"pageIndex":44, "rects":[[x1,y1,x2,y2],...]}` — PDF 物理坐标，左下角原点
- `sortIndex`：`"00044|003653|00262"` — 页码|文本偏移|距页顶Y，零填充，用于按阅读顺序排序
- `annotationText`：Zotero 已自动从 PDF 文本层提取的选中文字
- `annotationComment`：用户对标注额外写的批注
- `annotationType`：`highlight` / `underline` / `note` / `text` / `ink`
- `annotationPageLabel`：人类可读页码

### 数据目录查找逻辑

```
1. 从 %APPDATA%\Zotero\Zotero\Profiles\<profile>.default\prefs.js 读
2. 检查 extensions.zotero.useDataDir 是否为 true → 使用 extensions.zotero.dataDir
3. 否则使用 %USERPROFILE%\Zotero
4. 前端可手动指定覆盖
```

### 安全约束

- zotero.sqlite 必须先复制到临时目录，以只读模式打开，避免干扰运行中的 Zotero
- 不直接写入 zotero.sqlite，所有改动限于本项目的 workspace

## 后端设计

### 新增模块：`src/kn_graph/services/zotero_scanner.py`

```
scan_zotero(data_dir: str) -> ZoteroScanResult
  - 复制 zotero.sqlite 到 tempfile 临时目录
  - 只读连接，执行聚合查询
  - 按文献条目聚合，构建结构化结果
  - 只返回有 PDF 附件的条目

import_zotero_items(data_dir: str, item_ids: list[int], library_id: str) -> list[str]
  - 对每个选中条目创建 pipeline job
  - options 携带完整 Zotero 元数据
  - 返回 job_id 列表
```

#### 扫描查询逻辑

核心查询：从 `items` 出发关联所有子表，过滤掉附件/笔记/标注类型的条目，仅保留文献类型条目，且必须有至少一个 PDF 附件。

返回每条文献的聚合数据：
- itemID, key, itemType（如 journalArticle）
- 字段值字典（标题、DOI、日期、期刊名、卷、期、页码、摘要等）— 来自 EAV 结构
- 作者列表（firstName, lastName, creatorType）
- 附件列表（itemID, path, contentType）
- 笔记列表（itemID, note 内容）
- 标注列表（itemID, type, text, comment, pageLabel, sortIndex, color）— 按所属 PDF 附件分组
- 所属文件夹列表（collectionID, collectionName）

### 新增 API 端点

在 `src/kn_graph/routers/literature.py` 新增：

**POST `/literature/zotero/scan`**

请求：`{ "data_dir": "C:\\Users\\xxx\\Zotero" }`

响应：`{ "items": [...], "total_count": N, "collections": [...] }`

**POST `/literature/zotero/import`**

请求：`{ "data_dir": "...", "item_ids": [1,2,3], "library_id": "spl" }`

响应：`{ "job_ids": ["job_1", "job_2", "job_3"], "count": 3 }`

### 导入执行流程

对每个选中的条目：

1. 创建 pipeline job，`options` 携带：
   - `zotero_metadata`：完整 Zotero 元数据字典
   - `zotero_notes`：笔记列表
   - `zotero_annotations`：标注列表（已按 sortIndex 排序）
2. PDF 复制到 workspace 的 `corpus/papers/<paper_key>/source/`
3. Mineru 解析 PDF → 生成 markdown + HTML
4. 编组阶段（`materializing_paper`）：在 markdown 末尾追加 Zotero 笔记和标注（按页码分组）
   ```markdown
   ## Zotero 笔记
   > 用户的独立笔记内容...

   ## Zotero 标注
   ### 第 45 页
   > highlighted text passage  （黄色高亮 #ffd400）
   用户批注：这里的上下文需要额外注意

   ### 第 47 页
   > another highlighted passage  （蓝色下划线）
   ```
5. 提取阶段（`extracting_entities`）：Zotero 元数据优先填充；仅 Zotero 缺失的字段由模型提取
6. Job 状态更新为 `completed`

### 元数据优先级规则

| 字段类型 | 优先级 |
|----------|--------|
| 标题 | Zotero > Mineru MD H1 > 模型提取 |
| DOI | Zotero > 模型提取 |
| 作者 | Zotero > 模型提取 |
| 期刊/出版地 | Zotero > 模型提取 |
| 年份/日期 | Zotero > 模型提取 |
| 卷/期/页码 | Zotero > 模型提取 |
| 摘要 | Zotero > 模型提取 |
| 变量/关系/效应 | 仅模型提取（Zotero 无此概念） |

### 新增 Pydantic 模型

```python
class ZoteroScanRequest(BaseModel):
    data_dir: str = ""

class ZoteroItemInfo(BaseModel):
    item_id: int
    key: str
    item_type: str              # journalArticle, book, etc.
    title: str
    creators: list[dict]        # [{firstName, lastName, creatorType}]
    date: str
    publication_title: str
    volume: str
    issue: str
    pages: str
    doi: str
    abstract: str
    url: str
    pdf_paths: list[str]        # 解析后的绝对路径
    note_count: int
    annotation_count: int
    collections: list[str]      # 所属文件夹名

class ZoteroScanResponse(BaseModel):
    items: list[ZoteroItemInfo]
    total_count: int
    collections: list[dict]     # [{collection_id, name, parent_id, item_count}]

class ZoteroImportRequest(BaseModel):
    data_dir: str
    item_ids: list[int]
    library_id: str

class ZoteroImportResponse(BaseModel):
    job_ids: list[str]
    count: int
```

## 前端设计

### 新增组件：`scholarai-workbench/src/components/ZoteroImportModal.tsx`

全屏大弹窗，三栏布局 + 顶部路径栏 + 底部操作栏。

**顶部栏：**
- Zotero 数据目录输入框（默认填充自动检测的路径）
- "扫描"按钮（调用 scan API）
- 扫描进度提示

**左栏（w-56，文件夹树）：**
- 树形结构渲染 collections
- 每个节点显示文件夹名 + 条目数
- Checkbox 多选，用于过滤中栏列表
- 支持"全部"/"未分类"快捷选项

**中栏（flex-1，文献表格）：**
- 表头：复选框 | 标题 | 作者 | 年份 | 类型 | PDF | 笔记 | 标注
- 每行数据，复选框控制选中
- 表头复选框 = 全选/取消全选
- 搜索框（前端过滤，按标题/作者匹配）
- 底部显示已选数量

**右栏（w-80，详情预览）：**
- 选中条目时展示完整元数据
- 笔记内容预览（前 500 字）
- 标注预览（按页码分组，前 200 字）

**底部栏：**
- 目标文献库下拉选择器（列出所有 library）
- "导入选中 (N)" 按钮
- 取消按钮

**交互流程：**
1. 打开弹窗 → 自动尝试检测数据目录 → 用户确认/修改 → 点击扫描
2. 扫描完成 → 三栏展示数据 → 用户浏览筛选勾选
3. 选择目标文献库 → 点击"导入选中"
4. 调用 import API → 弹窗底部显示"5 个任务已提交，关闭弹窗后可在任务列表中查看进度"
5. 用户关闭弹窗 → PipelineView 任务表格自动刷新

### PipelineView.tsx 修改

在上传 PDF 卡片区域增加一个按钮：

```
[上传 PDF]  [从 Zotero 导入]
```

点击打开 ZoteroImportModal。弹窗关闭后触发任务列表刷新。

### API 新增函数（api.ts）

```typescript
// api.zotero namespace
scanZotero(dataDir: string): Promise<ZoteroScanResponse>
importZoteroItems(dataDir: string, itemIds: number[], libraryId: string): Promise<ZoteroImportResponse>
```

### 类型新增（types.ts）

```typescript
interface ZoteroItemInfo {
  item_id: number; key: string; item_type: string;
  title: string; creators: CreatorInfo[]; date: string;
  publication_title: string; volume: string; issue: string;
  pages: string; doi: string; abstract: string;
  pdf_paths: string[]; note_count: number; annotation_count: number;
  collections: string[];
}

// etc.
```

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `src/kn_graph/services/zotero_scanner.py` | 新增 | 扫描 + 导入逻辑 |
| `src/kn_graph/routers/literature.py` | 修改 | 新增 /zotero/scan 和 /zotero/import |
| `src/kn_graph/models/literature.py` | 修改 | 新增 Zotero 相关 Pydantic 模型 |
| `scholarai-workbench/src/components/ZoteroImportModal.tsx` | 新增 | 弹窗组件 |
| `scholarai-workbench/src/components/PipelineView.tsx` | 修改 | 新增"从 Zotero 导入"按钮 |
| `scholarai-workbench/src/api.ts` | 修改 | 新增 scanZotero / importZoteroItems |
| `scholarai-workbench/src/types.ts` | 修改 | 新增 Zotero 相关类型 |

## 不含

- 不修改 `frontend/` 目录（已废弃）
- 不修改 ChromaDB / FTS5 索引逻辑（复用现有）
- 不修改 Mineru 解析逻辑
- 不支持 Zotero 群组库的在线同步读取（仅本地）
- 不支持 Zotero 7 的 EPUB/快照附件（仅 PDF）
