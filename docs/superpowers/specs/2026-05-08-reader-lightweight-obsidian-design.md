# Reader 轻量化 Obsidian 设计

## 概述

将 Reader 模块从当前的"两跳 API 发现 + textarea"架构改造为"文件系统直读 + CodeMirror 6 编辑"，并加入标签页、大纲、Wiki Link + KG 打通、反链，使阅读编辑体验接近 Obsidian。

## 架构简化：去 API 发现层

### 现状

```
paperId → GET /paper/{id}/files → API 返回文件路径列表
→ localStorage 缓存 (24h TTL, validateCachedFiles bug)
→ Electron readLocalText 读文件
```

三步 I/O（API → 路径发现 → 读内容），中间夹一层易出错的缓存。

### 改为

```
paperId → Electron 主进程按约定路径直接探文件 (.md → .pdf → .html)
→ 读到内容 + 类型 → 回传渲染进程
```

在 preload 或主进程新增 `resolvePaperFile(paperId, libraryId)` 方法。不缓存结果，每次实时文件系统状态。

### 删除

- `DocumentResolver.ts` 中的 `resolvePaperFiles` API 调用、`FILES_CACHE_KEY`、`getCachedFiles`/`setCachedFiles`、`validateCachedFiles`
- Electron 端不再调用 `GET /paper/{id}/files`（API 端点保留给浏览器端）

### ViewerHost 启动流程

```
Electron resolvePaperFile(paperId, libraryId) → { type, data, path }
→ 直接渲染 PdfViewer 或 MarkdownEditor
```

## 编辑器：CodeMirror 6

### 模式

1. **Edit（源码模式）** — CM6 带 markdown 语法高亮、行号、括号匹配、自动缩进
2. **Live Preview（实时预览）** — CM6 markdown 编辑器内置：隐藏 `**` `##` 等标记，内联渲染图片/公式/链接。光标进入格式区域则展开标记。单一面板，不需要 split 分屏
3. **Read（阅读模式）** — MarkdownIt 渲染 + 大纲导航

### 文件变更

- `MarkdownEditor.tsx` — 重写，CM6 EditorView 替换 textarea
- 保留 `resolveLocalResourceUrl` 图片本地解析逻辑
- 保留 Reader Notes 内嵌 blockquote 机制
- 保留翻译弹窗、选中文本 popover
- `NoteMarkdownSync.ts` — 保留，接口不动
- `ReaderNotesManager.ts` — 保留

### 新增依赖

```json
{
  "@codemirror/view": "^6.x",
  "@codemirror/state": "^6.x",
  "@codemirror/lang-markdown": "^6.x",
  "@codemirror/commands": "^6.x",
  "@codemirror/language": "^6.x",
  "@codemirror/search": "^6.x",
  "@lezer/highlight": "^1.x"
}
```

### 文件保存策略

- CM6 `updateListener` 每次文档变更立即写盘（去 350ms debounce）
- `fs.watch` 监听外部变更，仅在本地无未保存修改时更新编辑器
- 去 800ms 轮询

## 标签页

ReaderView 顶部增加 TabBar，支持同时打开多篇文档：

```
ReaderView (shell)
├── TabBar                          ← 新增
│   ├── Tab[paper_A.md] [×]
│   ├── Tab[paper_B.pdf] [×]
│   └── Tab[paper_C.md] [×]
└── ViewerHost (当前激活的 tab)
```

- 标签数据存在 App 层 context：`{ id, paperId, libraryId, type, path, title }[]`
- 上限 8 个，超出关闭最旧未访问的
- 切换标签保留滚动位置（组件不销毁）
- PDF 和 Markdown 共用同一 TabBar
- 新增 `TabBar.tsx`

## 大纲

Read 模式下左侧 sticky 目录，解析 markdown h1-h6：

- 点击标题锚点跳转
- 当前阅读位置的标题高亮（IntersectionObserver）
- PDF 模式从 pdf.js document outline 获取
- 新增 `Outline.tsx`（CM6 已有解析能力，薄封装）

## Wiki Link + KG 打通

### 语法

沿用 Obsidian `[[link]]` 语法，目标类型：

| 语法 | 目标 | 点击行为 |
|------|------|---------|
| `[[变量名]]` | KG 节点 | 跳转 Graph View 高亮 |
| `[[@论文ID]]` | 论文 | 新标签页打开 md/pdf |
| `[[路径/文件.md]]` | 本地文件（绝对/相对） | 新标签页打开 |
| `[[名\|别名]]` | 任意 | 显示别名，行为同上 |

### 补全

CM6 输入 `[[` 触发 autocomplete，候选来源：
1. KG API 变量节点（按名称匹配）
2. 论文列表（按标题匹配）
3. 当前文档 heading
4. 本地文件路径（fallback）

### 渲染

Read/Live Preview 模式 `[[xxx]]` 渲染为蓝色可点击链接。

## 反链

Obsidian 逻辑：全 workspace 所有 .md 文件中搜索 `[[@当前论文ID]]` 字符串。

```
当前阅读: @Smith2023 的 md 文件
反链面板:
├── @Chen2024.md — 第 42 行: "如 [[@Smith2023]] 所示..."
├── @Liu2025.md — 第 108 行: "不同于 [[@Smith2023]] 的结论..."
```

Electron 主进程遍历 workspace .md 文件做 grep。新增 `BacklinksPanel.tsx`。

## 相关实体

从 `graph_views.json` 读取当前论文关联的 KG 节点（变量、效应、关系）。独立面板，与反链并列。

| 面板 | 数据来源 | 内容 |
|------|---------|------|
| 相关实体 | `graph_views.json` | 这篇论文抽取出的变量、效应 |
| 反链 | 全 workspace .md 文件 grep | 哪些文件 link 了这篇论文 |

## 搜索

CM6 `@codemirror/search` 自带：`Ctrl+F` 搜索面板、`Ctrl+H` 替换、正则、大小写。无需额外开发。

## 组件树（变更后）

```
ReaderView (shell)
├── TabBar                              ← 新增
└── ViewerHost (per active tab)
    ├── PdfViewer                       ← 基本不动
    └── MarkdownEditor (CM6 重写)        ← 核心改造
        ├── Outline (左侧 sticky)        ← 新增
        ├── SelectionActionPopover      ← 保留
        └── TranslationModal            ← 保留
    ├── RelatedEntities (右侧面板)       ← 新增
    ├── BacklinksPanel (右侧面板)        ← 新增
    ├── AnnotationSidebar               ← 保留
    └── ReaderChatSidebar               ← 保留
```

## 文件变更清单

| 文件 | 动作 |
|------|------|
| `DocumentResolver.ts` | 大幅精简，去 API/缓存，加 Electron 直读 |
| `MarkdownEditor.tsx` | 重写，CM6 替换 textarea |
| `ViewerHost.tsx` | 改写，适配新 resolver，加面板 |
| `ReaderView.tsx` | 改造，加 TabBar 状态管理 |
| `TabBar.tsx` | 新增 |
| `Outline.tsx` | 新增 |
| `RelatedEntities.tsx` | 新增 |
| `BacklinksPanel.tsx` | 新增 |
| `NoteMarkdownSync.ts` | 保留，接口不动 |
| `ReaderNotesManager.ts` | 保留 |
| `AnnotationSidebar.tsx` | 保留 |
| `PdfViewer.tsx` | 保留，微调适配 tab |
| `types.ts` | 加 tab/outline/backlink 类型 |
| `package.json` | 加 CM6 依赖 |

## 实现顺序

1. **架构简化** — 去 API 层，Electron 直读文件
2. **CM6 编辑器** — textarea → CodeMirror 6（含搜索）
3. **文件监听** — fs.watch 替换轮询
4. **标签页** — TabBar + 多文档切换
5. **大纲** — sticky 目录导航
6. **Wiki Link** — `[[补全 + 渲染 + 点击跳转]]`
7. **反链** — grep workspace .md 文件
8. **相关实体** — graph_views.json 面板
