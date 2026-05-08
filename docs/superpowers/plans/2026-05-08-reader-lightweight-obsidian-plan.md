# Reader 轻量化 Obsidian 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Reader 从"API 发现 + textarea"改造为"Electron 直读文件 + CodeMirror 6 + 标签页 + Wiki Link + 反链"

**Architecture:** Electron 主进程直接按约定路径探文件，渲染进程通过 CM6 编辑。标签页管理多文档。Wiki link 连 KG。反链通过 Electron grep workspace 实现。

**Tech Stack:** CodeMirror 6 (已安装), React 19, Electron 31, TypeScript, Tailwind CSS 4

---

## 文件变更总览

| 文件 | 动作 |
|------|------|
| `electron/main.cjs` | 加 IPC: resolve-paper-file, grep-workspace, watch-file, unwatch-file |
| `electron/preload.cjs` | 暴露新 IPC 到 desktopShell |
| `src/components/reader/DocumentResolver.ts` | **重写** — 去 API/缓存，用 Electron 直读 |
| `src/components/reader/MarkdownEditor.tsx` | **重写** — CM6 替换 textarea |
| `src/components/reader/ViewerHost.tsx` | **改造** — 适配新 resolver，加面板入口 |
| `src/components/reader/types.ts` | 加 TabDescriptor, BacklinkEntry |
| `src/components/reader/TabBar.tsx` | **新增** |
| `src/components/reader/Outline.tsx` | **新增** |
| `src/components/reader/BacklinksPanel.tsx` | **新增** |
| `src/components/reader/RelatedEntities.tsx` | **新增** |
| `src/components/reader/WikiLink.ts` | **新增** — CM6 wiki link extension |
| `src/components/ReaderView.tsx` | **改造** — 加 TabBar + 面板布局 |
| `src/App.tsx` | 加 tab 状态到 context |
| `src/components/reader/NoteMarkdownSync.ts` | 保留 |
| `src/components/reader/ReaderNotesManager.ts` | 保留 |
| `src/components/reader/AnnotationSidebar.tsx` | 保留 |
| `src/components/reader/PdfViewer.tsx` | 保留 |

---

### Task 1: Electron 直读文件 — 架构简化

**Files:**
- Modify: `electron/main.cjs` — 加 `resolve-paper-file` IPC
- Modify: `electron/preload.cjs` — 暴露 `resolvePaperFile`
- Rewrite: `src/components/reader/DocumentResolver.ts`
- Modify: `src/components/reader/ViewerHost.tsx` — 适配新接口
- Modify: `src/components/reader/types.ts` — 精简

- [ ] **Step 1: 在 Electron 主进程添加 resolve-paper-file IPC handler**

在 `electron/main.cjs` 的 IPC handlers 区域（`read-local-text` handler 之后）添加：

```javascript
// Resolve a paper's readable file by probing known paths in order: .md, .pdf, .html
// Returns: { ok: true, type: 'markdown'|'pdf'|'html', path, data?, size? }
// or:     { ok: false, error: 'not_found' }
ipcMain.handle("resolve-paper-file", async (_evt, paperId, libraryId) => {
  const pid = String(paperId || "").trim();
  const libId = String(libraryId || "").trim();
  if (!pid) return { ok: false, error: "empty_paper_id" };

  const repoRoot = getRepoRoot();
  const dataDir = process.env.KN_GRAPH_DATA_DIR || (process.platform === "win32" ? "D:\\KNGraphApp" : path.join(process.env.HOME || process.env.USERPROFILE || ".", ".kn_graph"));
  const wsDir = path.join(dataDir, "libraries", "workspaces");

  // Determine workspace dir — use libraryId if given, otherwise scan
  let libDirs = [];
  if (libId) {
    const d = path.join(wsDir, libId);
    if (fs.existsSync(d)) libDirs = [d];
  }
  if (!libDirs.length) {
    // Fallback: scan all workspace dirs
    try {
      libDirs = fs.readdirSync(wsDir, { withFileTypes: true })
        .filter(e => e.isDirectory())
        .map(e => path.join(wsDir, e.name));
    } catch (_e) { libDirs = []; }
  }

  // Read paper metadata from kn_gragh.db in each workspace to find file paths
  const Database = require("better-sqlite3");
  for (const ws of libDirs) {
    const dbPath = path.join(ws, "kn_gragh.db");
    if (!fs.existsSync(dbPath)) continue;
    let db = null;
    try {
      db = new Database(dbPath, { readonly: true });
      const row = db.prepare(
        "SELECT source_md_path, source_pdf_path, source_html_path FROM papers WHERE paper_id = ?"
      ).get(pid);
      if (!row) { db.close(); continue; }

      const candidates = [
        { key: "markdown", p: String(row.source_md_path || "").trim() },
        { key: "pdf", p: String(row.source_pdf_path || "").trim() },
        { key: "html", p: String(row.source_html_path || "").trim() },
      ];

      for (const c of candidates) {
        if (!c.p) continue;
        if (c.p.startsWith("storage://")) c.p = c.p.slice("storage://".length);
        const absPath = path.isAbsolute(c.p) ? c.p : path.resolve(repoRoot, c.p);
        if (!fs.existsSync(absPath) || !fs.statSync(absPath).isFile()) continue;

        if (c.key === "pdf") {
          const buf = fs.readFileSync(absPath);
          db.close();
          return {
            ok: true,
            type: "pdf",
            path: absPath,
            name: path.basename(absPath),
            data: buf.toString("base64"),
            size: buf.length,
          };
        }
        // markdown or html — read as text
        const text = fs.readFileSync(absPath, "utf8");
        db.close();
        return {
          ok: true,
          type: c.key,
          path: absPath,
          name: path.basename(absPath),
          data: text,
          size: Buffer.byteLength(text, "utf8"),
        };
      }
      db.close();
    } catch (_e) {
      if (db) { try { db.close(); } catch (_x) {} }
      continue;
    }
  }

  return { ok: false, error: "not_found" };
});
```

注意：`better-sqlite3` 可能不可用。改用 Node.js 内置的同步 SQLite 方式需要额外绑定。替代方案：读取 workspace 下的 `graph_views.json` 从中获取 paper_map 里的路径。但 graph_views.json 不含 `source_md_path`。更简单的方案是直接读取 `kn_gragh.db` 用原生 `fs` 做简单解析（SQLite 文件头的字符串可读），但不可靠。

**实际可行方案：** 先用 `node:sqlite` (Node.js 22.5+ 内置的同步 SQLite API，Electron 31 基于 Node 20 不可用)。退而求其次：在 preload 中暴露一个新的 IPC 让渲染进程仍调用后端 `/paper/{id}/files` API 但仅用来获取路径，然后由主进程读文件。这样保留了 API 路径发现但去掉了前端缓存层。

```javascript
// 实际可行方案：两个 IPC 配合
// 1) resolve-paper-paths: 仍调后端 API 获取文件路径列表（但去掉缓存）
// 2) resolve-paper-file: 接收路径数组，逐个尝试读取

ipcMain.handle("resolve-paper-paths", async (_evt, paperId, libraryId) => {
  const pid = encodeURIComponent(String(paperId || "").trim());
  const lib = encodeURIComponent(String(libraryId || "").trim());
  const params = lib ? `?library_id=${lib}` : "";
  const url = `http://${HOST}:${runtimePort}/paper/${pid}/files${params}`;

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (!resp.ok) return { ok: false, status: resp.status };
    const payload = await resp.json();
    return { ok: true, ...payload };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("resolve-paper-file", async (_evt, filesPayload) => {
  const files = filesPayload?.files || {};
  const order = ["markdown", "pdf", "html"];
  for (const key of order) {
    const f = files[key];
    if (!f?.path) continue;
    const p = String(f.path).trim();
    if (!p || !fs.existsSync(p) || !fs.statSync(p).isFile()) continue;
    const name = path.basename(p);
    if (key === "pdf") {
      const buf = fs.readFileSync(p);
      return { ok: true, type: "pdf", path: p, name, data: buf.toString("base64"), size: buf.length };
    }
    const text = fs.readFileSync(p, "utf8");
    return { ok: true, type: key, path: p, name, data: text, size: Buffer.byteLength(text, "utf8") };
  }
  return { ok: false, error: "no_readable_file" };
});
```

- [ ] **Step 2: 在 preload.cjs 暴露新 IPC**

在 `electron/preload.cjs` 的 `contextBridge.exposeInMainWorld("desktopShell", {...})` 对象中添加：

```javascript
resolvePaperPaths: (paperId, libraryId) => ipcRenderer.invoke("resolve-paper-paths", paperId, libraryId),
resolvePaper: (filesPayload) => ipcRenderer.invoke("resolve-paper-file", filesPayload),
```

- [ ] **Step 3: 重写 DocumentResolver.ts**

删除全部缓存逻辑、API 调用。只保留 `electronReadFile`、`electronReadText` 辅助函数。新接口：

```typescript
// DocumentResolver.ts (rewritten)
// Single entry point: resolve and load a paper's readable file in one step.
// No caching — file system is the source of truth.

export interface ResolvedDocument {
  type: 'pdf' | 'markdown' | 'html' | 'none';
  data: Uint8Array | string | null;
  file_name: string;
  absolute_path: string;
}

async function electronReadBinary(path: string): Promise<Uint8Array | null> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return null;
  const result = await shell.readLocalFile(path);
  if (!result.ok || !result.data) return null;
  const binary = atob(result.data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export async function resolveAndLoadDocument(
  paperId: string,
  libraryId: string,
  rawPaperId?: string,
  preferredType?: 'pdf' | 'markdown' | 'html' | null,
): Promise<ResolvedDocument> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') {
    throw new Error('reader_requires_electron_runtime');
  }

  // Step 1: get file paths (one-time, no cache)
  let pathsResult = await shell.resolvePaperPaths(paperId, libraryId);
  if (!pathsResult.ok && rawPaperId && rawPaperId !== paperId) {
    pathsResult = await shell.resolvePaperPaths(rawPaperId, libraryId);
  }
  if (!pathsResult.ok) {
    return { type: 'none', data: null, file_name: '', absolute_path: '' };
  }

  const files = (pathsResult.files || {}) as Record<string, { path: string; name: string; size_bytes: number }>;

  // Step 2: read file content, respecting preferredType
  const order = preferredType
    ? [preferredType, ...['pdf', 'markdown', 'html'].filter(t => t !== preferredType)]
    : ['pdf', 'markdown', 'html'];

  for (const t of order) {
    const f = files[t];
    if (!f?.path) continue;
    if (t === 'pdf') {
      const data = await electronReadBinary(f.path);
      if (data) return { type: 'pdf', data, file_name: f.name, absolute_path: f.path };
    } else {
      const result = await shell.readLocalText(f.path);
      if (result.ok && result.data != null) {
        return { type: t as 'markdown' | 'html', data: result.data, file_name: f.name, absolute_path: f.path };
      }
    }
  }

  return { type: 'none', data: null, file_name: '', absolute_path: '' };
}
```

- [ ] **Step 4: 精简 types.ts**

在 `src/components/reader/types.ts` 中删除不再需要的 `DocumentLoadResult`（已在 DocumentResolver 中重新定义），添加后续任务需要的类型：

```typescript
// 删除: DocumentLoadResult (移到 DocumentResolver.ts 作为 ResolvedDocument)

// 新增:
export interface TabDescriptor {
  id: string;                // unique tab id (uuid)
  paperId: string;
  libraryId: string;
  type: 'pdf' | 'markdown' | 'html';
  path: string;
  title: string;             // display name (file name or paper title)
}

export interface BacklinkEntry {
  filePath: string;
  fileName: string;
  lineNumber: number;
  snippet: string;           // surrounding context of the [[link]]
  paperId?: string;          // extracted paper ID from the referencing file
}

export interface OutlineItem {
  level: number;             // 1-6 for h1-h6
  text: string;
  line: number;              // source line number
  id: string;                // anchor id
}
```

- [ ] **Step 5: 更新 ViewerHost.tsx 使用新接口**

`ViewerHost.tsx` 中：
- 将 `resolvePaperFiles` + `loadDocument` 两步替换为单次 `resolveAndLoadDocument`
- 删除 `paperFiles` 状态（不再需要中间文件列表）
- 简化 `useEffect` 启动逻辑：

```typescript
// ViewerHost.tsx — 替换 imports
import { resolveAndLoadDocument } from './DocumentResolver';
import type { ResolvedDocument } from './DocumentResolver';

// 替换 paperFiles state
const [document, setDocument] = useState<ResolvedDocument | null>(null);

// 简化 useEffect
useEffect(() => {
  if (!paperId) return;
  let cancelled = false;
  setLoading(true);
  setError(null);

  resolveAndLoadDocument(paperId, libraryId, rawPaperId, preferredType)
    .then((doc) => {
      if (cancelled) return;
      setDocument(doc);
      onDocumentMeta?.({
        absolutePath: doc.absolute_path || '',
        fileName: doc.file_name || '',
        type: doc.type,
      });
      setLoading(false);
    })
    .catch((e) => {
      if (cancelled) return;
      setError(e.message);
      setLoading(false);
    });

  return () => { cancelled = true; };
}, [paperId, libraryId, preferredType, rawPaperId, onDocumentMeta]);
```

其余渲染逻辑不变（`document.type === 'none'` → "No readable file"，等等）。

- [ ] **测试验证: 启动 Electron 应用，打开一篇已导入论文的 .md 文件**

1. `npm run dev:electron`
2. 在 Library View 选一篇论文，点击打开 Reader
3. 确认: 不再显示 "No readable file available"
4. 确认: 文件内容正常加载显示
5. 打开 DevTools → Application → Local Storage，确认 `kn_reader_paper_files_cache_v1` 不再出现

- [ ] **Step 6: 提交**

```bash
git add electron/main.cjs electron/preload.cjs \
  scholarai-workbench/src/components/reader/DocumentResolver.ts \
  scholarai-workbench/src/components/reader/ViewerHost.tsx \
  scholarai-workbench/src/components/reader/types.ts
git commit -m "refactor: replace API file-discovery with Electron direct read, remove cache layer"
```

---

### Task 2: CodeMirror 6 编辑器

**Files:**
- Rewrite: `src/components/reader/MarkdownEditor.tsx`
- Create: `src/components/reader/WikiLink.ts` — CM6 wiki link extension (placeholder, 实现在 Task 6)

- [ ] **Step 1: 重写 MarkdownEditor.tsx — 基础 CM6 设置**

```typescript
import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { syntaxHighlighting, defaultHighlightStyle, bracketMatching } from '@codemirror/language';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import { closeBrackets } from '@codemirror/autocomplete';
import { languages } from '@codemirror/language-data';
import MarkdownIt from 'markdown-it';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTaskLists from 'markdown-it-task-lists';
import markdownItMark from 'markdown-it-mark';
import markdownItDeflist from 'markdown-it-deflist';
import markdownItKatex from 'markdown-it-katex';
import DOMPurify from 'dompurify';
import 'katex/dist/katex.min.css';
import type { ViewerMode } from './types';
import SelectionActionPopover from './SelectionActionPopover';
import TranslationModal from './TranslationModal';
import { api } from '../../api';
import { readerNotesManager } from './ReaderNotesManager';
import {
  addNoteToMarkdownAtomic,
  addNoteToMarkdownAtomicByLine,
  deleteNoteFromMarkdownAny,
  extractNoteBlocks,
  listRecordedNotesMarkdownPaths,
  readMarkdownText,
  setRecordedNotesMarkdownPath,
} from './NoteMarkdownSync';

interface MarkdownEditorProps {
  paperId: string;
  libraryId: string;
  content: string;
  fileName: string;
  absolutePath: string;
  mode?: ViewerMode;
  onModeChange?: (mode: ViewerMode) => void;
  onContentChange?: (content: string) => void;
}

export default function MarkdownEditor({
  paperId,
  libraryId,
  content,
  fileName,
  absolutePath,
  mode: initialMode = 'read',
  onModeChange,
  onContentChange,
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<ViewerMode>(initialMode);
  const [renderedHtml, setRenderedHtml] = useState('');
  const [noteRanges, setNoteRanges] = useState<Array<{ start: number; end: number; id: string; quote: string; note: string }>>([]);
  const [selectionUI, setSelectionUI] = useState({ visible: false, x: 0, y: 0, text: '', lineEnd: -1 });
  const [translationOpen, setTranslationOpen] = useState(false);
  const [translationText, setTranslationText] = useState('');

  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);
  const readContainerRef = useRef<HTMLDivElement>(null);

  // --- MarkdownIt instance (for Read mode rendering) ---
  const md = useMemo(() => (
    new MarkdownIt({ html: true, linkify: true, typographer: true, breaks: false })
      .use(markdownItFootnote)
      .use(markdownItTaskLists, { enabled: true, label: true })
      .use(markdownItMark)
      .use(markdownItDeflist)
      .use(markdownItKatex)
  ), []);

  // --- CM6 editor setup/destroy ---
  const currentContentRef = useRef(content);

  const createEditor = useCallback((container: HTMLElement, initialText: string, extensions: any[]) => {
    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        const text = update.state.doc.toString();
        currentContentRef.current = text;
        onContentChange?.(text);
      }
    });

    const state = EditorState.create({
      doc: initialText,
      extensions: [
        ...extensions,
        updateListener,
        keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]),
        history(),
        syntaxHighlighting(defaultHighlightStyle),
        bracketMatching(),
        closeBrackets(),
        highlightSelectionMatches(),
      ],
    });

    return new EditorView({ state, parent: container });
  }, [onContentChange]);

  // --- Initialize/destroy CM6 when entering Edit or LivePreview mode ---
  useEffect(() => {
    const container = editorContainerRef.current;
    if (!container) return;
    const isCmMode = mode === 'edit' || mode === 'live-preview';

    if (isCmMode && !editorViewRef.current) {
      const extensions: any[] = [
        lineNumbers(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        markdown({ base: markdownLanguage, codeLanguages: languages }),
      ];
      editorViewRef.current = createEditor(container, currentContentRef.current, extensions);
    } else if (!isCmMode && editorViewRef.current) {
      editorViewRef.current.destroy();
      editorViewRef.current = null;
    }

    return () => {
      if (editorViewRef.current) {
        editorViewRef.current.destroy();
        editorViewRef.current = null;
      }
    };
  }, [mode, createEditor]);

  // --- Sync external content changes into CM6 ---
  useEffect(() => {
    const view = editorViewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (content !== current) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: content },
      });
    }
  }, [content]);

  // --- Auto-save to disk on every change (CM6 updateListener handles this above) ---
  useEffect(() => {
    if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
    if (mode === 'read') return;
    // Write to disk when content changes (debounced 150ms to avoid excessive writes)
    const timer = window.setTimeout(() => {
      window.desktopShell?.writeLocalText(absolutePath, currentContentRef.current);
    }, 150);
    return () => window.clearTimeout(timer);
  }, [content, absolutePath, mode]);

  // --- Read mode: poll file for external changes (will be replaced by fs.watch in Task 3) ---
  useEffect(() => {
    if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
    if (mode !== 'read') return;
    let cancelled = false;
    const tick = async () => {
      const r = await window.desktopShell?.readLocalText(absolutePath);
      if (cancelled || !r?.ok) return;
      const disk = String(r.data || '');
      if (disk !== currentContentRef.current) {
        currentContentRef.current = disk;
        onContentChange?.(disk);
      }
    };
    tick();
    const timer = window.setInterval(tick, 800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [absolutePath, mode, onContentChange]);

  // 以下逻辑完整保留自现有 MarkdownEditor.tsx，适配 CM6 的 DOM 结构：
  // - Read 模式 MarkdownIt 渲染（resolveLocalResourceUrl, toFileUrl, fileUrlToPath, guessMimeByPath 完整保留）
  // - DOMPurify sanitize + img/a src 重写 + note blockquote delete 按钮（完整保留）
  // - SelectionActionPopover 选中文本 → 翻译/笔记（适配 CM6 selection API）
  // - handleTranslate / handleSaveNote / handleDeleteNoteByIndex（完整保留）
  // - Reader Notes blockquote 内嵌: extractNoteBlocks, findReaderNoteRanges（完整保留）
  // - reader-note-md-deleted 事件监听（完整保留）
  // - Edit/LivePreview/Read 三模式切换按钮 JSX（完整保留）
  // 这些代码约 300 行，从现有 MarkdownEditor.tsx 原样迁入
```

注意：完整的 MarkdownEditor 重写约 400 行，上面是最关键的 CM6 初始化和模式切换逻辑。保留的现有逻辑见上方注释。

- [ ] **测试验证: 三模式切换 + 编辑 + 搜索**

1. 打开一篇 .md 论文
2. 切换 Edit → LivePreview → Read，确认三种模式均可渲染
3. Edit 模式下确认有行号、语法高亮
4. Ctrl+F 输入搜索词，确认高亮匹配项
5. 修改文本，确认 150ms 后磁盘文件更新
6. 用外部编辑器（如 notepad）修改同一文件，在 Read 模式下确认 800ms 内自动刷新

- [ ] **Step 2: 提交**

```bash
git add scholarai-workbench/src/components/reader/MarkdownEditor.tsx
git commit -m "feat: replace textarea with CodeMirror 6 editor for markdown"
```

---

### Task 3: 文件监听（fs.watch 替换轮询）

**Files:**
- Modify: `electron/main.cjs` — 加 watch-file / unwatch-file IPC
- Modify: `electron/preload.cjs` — 暴露 watchFile / unwatchFile
- Modify: `src/components/reader/MarkdownEditor.tsx` — 用 watch 替换轮询

- [ ] **Step 1: 在 Electron 主进程添加文件监听 IPC**

在 `electron/main.cjs` 的 IPC handlers 区域添加：

```javascript
const fileWatchers = new Map(); // path → FSWatcher

ipcMain.handle("watch-file", (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p || !fs.existsSync(p)) return { ok: false, error: "invalid_path" };
  if (fileWatchers.has(p)) return { ok: true }; // already watching

  try {
    const watcher = fs.watch(p, (eventType) => {
      if (eventType === "change") {
        // Notify renderer via webContents (mainWindow is the BrowserWindow ref)
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("file-changed", { path: p, event: "change" });
        }
      }
    });
    watcher.on("error", () => {
      fileWatchers.delete(p);
    });
    fileWatchers.set(p, watcher);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("unwatch-file", (_evt, filePath) => {
  const p = String(filePath || "").trim();
  const watcher = fileWatchers.get(p);
  if (watcher) {
    try { watcher.close(); } catch (_e) {}
    fileWatchers.delete(p);
  }
  return { ok: true };
});
```

- [ ] **Step 2: 在 preload.cjs 暴露**

```javascript
watchFile: (filePath) => ipcRenderer.invoke("watch-file", filePath),
unwatchFile: (filePath) => ipcRenderer.invoke("unwatch-file", filePath),
// Listen for file-changed events from main process
onFileChanged: (callback) => {
  const handler = (_evt, payload) => callback(payload);
  ipcRenderer.on("file-changed", handler);
  return () => ipcRenderer.removeListener("file-changed", handler);
},
```

- [ ] **Step 3: 更新 MarkdownEditor.tsx 使用 fs.watch**

删除 Read 模式的 800ms 轮询 useEffect，替换为：

```typescript
// Read mode: use fs.watch for external file changes
useEffect(() => {
  if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
  if (mode !== 'read') return;

  // Start watching
  window.desktopShell.watchFile(absolutePath);

  // Listen for changes
  const unsubscribe = window.desktopShell.onFileChanged((payload: { path: string; event: string }) => {
    if (payload.path !== absolutePath) return;
    window.desktopShell?.readLocalText(absolutePath).then((r: any) => {
      if (!r?.ok) return;
      const disk = String(r.data || '');
      if (disk !== currentContentRef.current) {
        currentContentRef.current = disk;
        onContentChange?.(disk);
      }
    });
  });

  return () => {
    unsubscribe();
    window.desktopShell?.unwatchFile(absolutePath);
  };
}, [absolutePath, mode, onContentChange]);
```

- [ ] **Step 4: 提交**

```bash
git add electron/main.cjs electron/preload.cjs \
  scholarai-workbench/src/components/reader/MarkdownEditor.tsx
git commit -m "feat: replace file polling with fs.watch for external change detection"
```

---

### Task 4: 标签页系统

**Files:**
- Create: `src/components/reader/TabBar.tsx`
- Modify: `src/components/ReaderView.tsx`
- Modify: `src/components/reader/types.ts` (TabDescriptor 已在 Task 1 添加)

- [ ] **Step 1: 创建 TabBar.tsx**

```typescript
import { X, FileText, FileType } from 'lucide-react';
import type { TabDescriptor } from './types';

interface TabBarProps {
  tabs: TabDescriptor[];
  activeTabId: string | null;
  onSelectTab: (tabId: string) => void;
  onCloseTab: (tabId: string) => void;
}

export default function TabBar({ tabs, activeTabId, onSelectTab, onCloseTab }: TabBarProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="flex items-center gap-0 px-2 py-0 border-b border-outline-variant bg-surface-container-lowest overflow-x-auto">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        const Icon = tab.type === 'pdf' ? FileType : FileText;
        return (
          <button
            key={tab.id}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-outline-variant transition-colors min-w-0 max-w-[200px] ${
              isActive
                ? 'bg-surface-container text-on-surface font-medium'
                : 'text-on-surface-variant hover:bg-surface-container-low'
            }`}
            onClick={() => onSelectTab(tab.id)}
            title={tab.path}
          >
            <Icon className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">{tab.title}</span>
            <X
              className="w-3 h-3 shrink-0 ml-0.5 hover:text-error rounded-sm"
              onClick={(e) => {
                e.stopPropagation();
                onCloseTab(tab.id);
              }}
            />
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: 改造 ReaderView.tsx 支持标签页**

```typescript
import { useState, useCallback } from 'react';
import { BookOpen, FileText, ArrowLeft } from 'lucide-react';
import { useApp } from '../App';
import ViewerHost from './reader/ViewerHost';
import TabBar from './reader/TabBar';
import type { TabDescriptor } from './reader/types';

const MAX_TABS = 8;

export default function ReaderView() {
  const [tabs, setTabs] = useState<TabDescriptor[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [docPath, setDocPath] = useState('');
  const {
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    setSelectedNodeId,
    setSelectedPaperRawId,
    setSelectedPaperPreferredType,
    selectedNodeId,
    selectedPaperPreferredType,
    selectedPaperRawId,
    readerReturnView,
    setCurrentView,
  } = useApp();

  // When a new paper is selected, open or focus a tab
  const openPaper = useCallback((paperId: string, libraryId: string, rawPaperId?: string, preferredType?: string | null) => {
    const existing = tabs.find(t => t.paperId === paperId);
    if (existing) {
      setActiveTabId(existing.id);
      return;
    }

    const newTab: TabDescriptor = {
      id: crypto.randomUUID(),
      paperId,
      libraryId: libraryId || selectedPaperLibraryId,
      type: (preferredType as TabDescriptor['type']) || 'markdown',
      path: '',
      title: paperId,
    };

    setTabs(prev => {
      const next = [...prev, newTab];
      if (next.length > MAX_TABS) return next.slice(next.length - MAX_TABS);
      return next;
    });
    setActiveTabId(newTab.id);
    setSelectedPaperId?.(null); // clear the trigger
  }, [tabs, selectedPaperLibraryId, setSelectedPaperId]);

  // Open paper from external trigger
  useEffect(() => {
    if (!selectedPaperId) return;
    openPaper(selectedPaperId, selectedPaperLibraryId, selectedPaperRawId || undefined, selectedPaperPreferredType);
  }, [selectedPaperId]);

  const closeTab = useCallback((tabId: string) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.id === tabId);
      const next = prev.filter(t => t.id !== tabId);
      if (activeTabId === tabId && next.length > 0) {
        const newIdx = Math.min(idx, next.length - 1);
        setActiveTabId(next[newIdx].id);
      } else if (next.length === 0) {
        setActiveTabId(null);
      }
      return next;
    });
  }, [activeTabId]);

  const activeTab = tabs.find(t => t.id === activeTabId) || null;

  const handleBack = () => {
    setSelectedPaperId(null);
    setSelectedPaperRawId(null);
    setSelectedPaperPreferredType(null);
    setSelectedNodeId(null);
    setCurrentView(readerReturnView);
  };

  if (!activeTab && !selectedNodeId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <BookOpen className="w-12 h-12 text-outline mx-auto" />
          <h3 className="text-lg font-medium text-on-surface">Document Reader</h3>
          <p className="text-sm text-on-surface-variant max-w-md">
            Select a paper from the Graph or Library view to read its full text.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <button
          className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          onClick={handleBack}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <span className="text-xs font-mono text-on-surface truncate max-w-[400px]">
          {activeTab?.paperId || selectedNodeId || 'Document'}
        </span>
        {docPath && (
          <span className="text-[10px] text-outline truncate ml-auto max-w-[48%]" title={docPath}>
            {docPath}
          </span>
        )}
      </div>

      <TabBar
        tabs={tabs}
        activeTabId={activeTabId}
        onSelectTab={setActiveTabId}
        onCloseTab={closeTab}
      />

      {activeTab ? (
        <ViewerHost
          key={activeTab.id}
          paperId={activeTab.paperId}
          libraryId={activeTab.libraryId}
          preferredType={selectedPaperPreferredType}
          rawPaperId={selectedPaperRawId || undefined}
          onDocumentMeta={(meta) => {
            setDocPath(meta.absolutePath || '');
            // Update tab metadata
            setTabs(prev => prev.map(t =>
              t.id === activeTab.id
                ? { ...t, path: meta.absolutePath || '', type: meta.type === 'none' ? t.type : meta.type, title: meta.fileName || t.title }
                : t
            ));
          }}
        />
      ) : selectedNodeId ? (
        <div className="flex-1 flex items-center justify-center bg-surface-container-low">
          <p className="text-sm text-on-surface-variant">Variable detail view — select a paper to open documents.</p>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 3: 提交**

```bash
git add scholarai-workbench/src/components/reader/TabBar.tsx \
  scholarai-workbench/src/components/ReaderView.tsx
git commit -m "feat: add tab system for multi-document editing in reader"
```

---

### Task 5: 大纲导航

**Files:**
- Create: `src/components/reader/Outline.tsx`

- [ ] **Step 1: 创建 Outline.tsx**

```typescript
import { useEffect, useState, useRef } from 'react';
import type { OutlineItem } from './types';

interface OutlineProps {
  content: string;       // raw markdown text
  activeLine?: number;   // current scroll position line
  onGoToLine?: (line: number) => void;
}

function parseOutline(text: string): OutlineItem[] {
  const lines = text.split('\n');
  const items: OutlineItem[] = [];
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^(#{1,6})\s+(.+)/);
    if (!match) continue;
    const level = match[1].length;
    const headingText = match[2].trim();
    const id = headingText.toLowerCase().replace(/[^\w一-鿿]+/g, '-').replace(/(^-|-$)/g, '');
    items.push({ level, text: headingText, line: i, id });
  }
  return items;
}

export default function Outline({ content, activeLine = -1, onGoToLine }: OutlineProps) {
  const [items, setItems] = useState<OutlineItem[]>([]);
  const activeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    setItems(parseOutline(content));
  }, [content]);

  // Auto-scroll active item into view
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [activeLine, items]);

  if (items.length === 0) {
    return (
      <div className="w-48 shrink-0 border-r border-outline-variant bg-surface-container-lowest p-3">
        <p className="text-xs text-outline">No headings found</p>
      </div>
    );
  }

  return (
    <div className="w-48 shrink-0 border-r border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-2">
        <h4 className="text-[11px] font-medium text-on-surface-variant px-1.5 py-1 mb-1">Outline</h4>
        {items.map((item) => {
          const isActive = activeLine >= 0 && item.line <= activeLine;
          const isExact = item.line === activeLine;
          return (
            <button
              key={`${item.line}-${item.text}`}
              ref={isExact ? activeRef : undefined}
              className={`block w-full text-left text-xs px-1.5 py-0.5 rounded truncate transition-colors hover:bg-surface-container-low ${
                isExact
                  ? 'text-primary font-medium bg-primary-container/30'
                  : isActive
                  ? 'text-on-surface'
                  : 'text-on-surface-variant'
              }`}
              style={{ paddingLeft: `${4 + (item.level - 1) * 12}px` }}
              onClick={() => onGoToLine?.(item.line)}
              title={item.text}
            >
              {item.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add scholarai-workbench/src/components/reader/Outline.tsx
git commit -m "feat: add outline navigation panel for markdown headings"
```

注意：Outline 组件需要在 MarkdownEditor 的 Read 模式中集成（左侧 sticky），在 MarkdownEditor 的渲染部分加 `<Outline>` 并传入 content 和当前滚动行。集成代码将在 MarkdownEditor 重写时一并包含。

---

### Task 6: Wiki Link 补全 + 渲染 + 点击

**Files:**
- Create: `src/components/reader/WikiLink.ts`
- Modify: `src/components/reader/MarkdownEditor.tsx` — 集成 CM6 wiki link extension

- [ ] **Step 1: 创建 WikiLink.ts — CM6 completion source + markdown syntax extension**

```typescript
import { CompletionContext, CompletionResult } from '@codemirror/autocomplete';
import { Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType } from '@codemirror/view';
import { RangeSetBuilder } from '@codemirror/state';
import type { GraphNode } from '../../types';

// === Completion source for [[ ===

let cachedNodes: Array<{ id: string; label: string }> = [];
let cacheTs = 0;
const CACHE_TTL = 30000; // 30s

async function fetchNodeCompletions(): Promise<Array<{ id: string; label: string }>> {
  const now = Date.now();
  if (now - cacheTs < CACHE_TTL && cachedNodes.length) return cachedNodes;

  try {
    // Reuse existing graph data from App context via a global or event
    // For now, fetch from API
    const resp = await fetch('/search?q=');
    if (!resp.ok) return cachedNodes;
    // This is a simplified placeholder — real impl uses graphData from AppContext
  } catch {
    // ignore
  }
  return cachedNodes;
}

export function setWikiLinkNodeCache(nodes: Array<{ id: string; label: string }>) {
  cachedNodes = nodes;
  cacheTs = Date.now();
}

export function wikiLinkCompletionSource(context: CompletionContext): CompletionResult | null {
  const before = context.matchBefore(/\[\[([^\]]*)$/);
  if (!before) return null;

  const query = before.text.slice(2).toLowerCase(); // strip leading [[
  const options: Array<{ label: string; type: string; detail: string }> = [];

  // KG nodes
  for (const node of cachedNodes) {
    const label = node.label || node.id;
    if (label.toLowerCase().includes(query)) {
      options.push({ label: `[[${label}]]`, type: 'variable', detail: `KG: ${node.id}` });
    }
  }

  // File paths (relative/absolute) — basic:
  if (query.includes('/') || query.includes('\\') || query.includes('.')) {
    options.push({ label: `[[${before.text.slice(2)}]]`, type: 'file', detail: 'local file' });
  }

  // Paper references (@ prefix)
  const paperQuery = query.startsWith('@') ? query.slice(1) : '';
  if (paperQuery) {
    options.push({ label: `[[@${paperQuery}]]`, type: 'paper', detail: 'paper reference' });
  }

  return {
    from: before.from,
    options: options.slice(0, 20),
    filter: false,
  };
}

// === Decoration: render [[link]] as styled links in LivePreview/Read mode ===

const wikiLinkRegex = /\[\[([^\]]+)\]\]/g;

class WikiLinkWidget extends WidgetType {
  constructor(readonly text: string, readonly target: string, readonly onNavigate: (target: string) => void) {
    super();
  }

  eq(other: WikiLinkWidget) {
    return other.target === this.target && other.text === this.text;
  }

  toDOM() {
    const span = document.createElement('span');
    span.className = 'wiki-link';
    span.textContent = this.text;
    span.style.cssText = 'color: #2563eb; cursor: pointer; text-decoration: underline; text-underline-offset: 2px;';
    span.title = this.target;
    span.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.onNavigate(this.target);
    });
    return span;
  }
}

export function wikiLinkDecoration(view: EditorView, onNavigate: (target: string) => void): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const text = view.state.doc.toString();
  let match: RegExpExecArray | null;

  wikiLinkRegex.lastIndex = 0;
  while ((match = wikiLinkRegex.exec(text)) !== null) {
    const fullMatch = match[0];
    const inner = match[1];
    const displayText = inner.includes('|') ? inner.split('|')[1] : inner;
    const linkTarget = inner.includes('|') ? inner.split('|')[0] : inner;

    const from = match.index;
    const to = from + fullMatch.length;

    builder.add(from, to, Decoration.replace({
      widget: new WikiLinkWidget(displayText, linkTarget, onNavigate),
      inclusive: false,
    }));
  }

  return builder.finish();
}

export const wikiLinkPlugin = (onNavigate: (target: string) => void) =>
  ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = wikiLinkDecoration(view, onNavigate);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = wikiLinkDecoration(update.view, onNavigate);
      }
    }
  }, {
    decorations: v => v.decorations,
  });
```

- [ ] **Step 2: 集成到 MarkdownEditor**

在 MarkdownEditor.tsx 的 CM6 初始化中：
1. 导入 `autocompletion` 和 wiki link 相关函数
2. 在 CM6 extensions 中添加：
```typescript
import { autocompletion } from '@codemirror/autocomplete';
import { wikiLinkCompletionSource, wikiLinkPlugin, setWikiLinkNodeCache } from './WikiLink';
import { useApp } from '../../App';

// Inside component:
const { graphData } = useApp();

// Seed wiki link completion cache from graph data
useEffect(() => {
  if (!graphData?.nodes) return;
  setWikiLinkNodeCache(
    graphData.nodes
      .filter(n => n.type === 'variable' && n.validated_variable)
      .map(n => ({ id: n.id, label: n.label || n.name || n.id }))
  );
}, [graphData]);

// Wiki link navigation handler
const handleWikiLinkNavigate = useCallback((target: string) => {
  if (target.startsWith('@')) {
    // Paper reference — open in new tab
    const paperId = target.slice(1);
    window.dispatchEvent(new CustomEvent('open-reader-tab', { detail: { paperId } }));
  } else if (target.includes('/') || target.includes('\\') || target.includes('.')) {
    // File path — open in new tab
    window.dispatchEvent(new CustomEvent('open-reader-file', { detail: { path: target } }));
  } else {
    // KG node — navigate to graph view
    window.dispatchEvent(new CustomEvent('navigate-to-node', { detail: { nodeId: target } }));
  }
}, []);

// Add to CM6 extensions:
autocompletion({ override: [wikiLinkCompletionSource] }),
wikiLinkPlugin(handleWikiLinkNavigate),
```

- [ ] **Step 3: 提交**

```bash
git add scholarai-workbench/src/components/reader/WikiLink.ts \
  scholarai-workbench/src/components/reader/MarkdownEditor.tsx
git commit -m "feat: add wiki link [[completion, rendering, and KG/file/paper navigation"
```

---

### Task 7: 反链面板

**Files:**
- Modify: `electron/main.cjs` — 加 grep-workspace IPC
- Modify: `electron/preload.cjs` — 暴露 grepWorkspace
- Create: `src/components/reader/BacklinksPanel.tsx`
- Modify: `src/components/reader/ViewerHost.tsx` — 加反链面板入口

- [ ] **Step 1: Electron 主进程添加 grep-workspace IPC**

在 `electron/main.cjs` 添加：

```javascript
// Grep workspace .md files for a pattern (e.g. [[@paperId]])
// Returns array of { filePath, fileName, lineNumber, snippet }
ipcMain.handle("grep-workspace", async (_evt, pattern, libraryId) => {
  const pat = String(pattern || "").trim();
  if (!pat) return { ok: false, error: "empty_pattern" };
  const libId = String(libraryId || "").trim();
  const dataDir = process.env.KN_GRAPH_DATA_DIR || (process.platform === "win32" ? "D:\\KNGraphApp" : path.join(process.env.HOME || process.env.USERPROFILE || ".", ".kn_graph"));
  const wsDir = path.join(dataDir, "libraries", "workspaces");

  let searchDirs = [];
  if (libId) {
    const d = path.join(wsDir, libId);
    if (fs.existsSync(d)) searchDirs = [d];
  } else {
    try {
      searchDirs = fs.readdirSync(wsDir, { withFileTypes: true })
        .filter(e => e.isDirectory())
        .map(e => path.join(wsDir, e.name));
    } catch (_e) { searchDirs = []; }
  }

  const results = [];
  const regex = new RegExp(pat.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');

  for (const dir of searchDirs) {
    const stack = [dir];
    while (stack.length > 0) {
      const cur = stack.pop();
      let entries = [];
      try { entries = fs.readdirSync(cur, { withFileTypes: true }); } catch (_e) { continue; }
      for (const entry of entries) {
        const full = path.join(cur, entry.name);
        if (entry.isDirectory()) { stack.push(full); continue; }
        if (entry.isFile() && entry.name.endsWith('.md')) {
          const text = fs.readFileSync(full, 'utf8');
          const lines = text.split('\n');
          for (let i = 0; i < lines.length; i++) {
            regex.lastIndex = 0;
            if (regex.test(lines[i])) {
              const start = Math.max(0, i - 1);
              const end = Math.min(lines.length, i + 2);
              results.push({
                filePath: full,
                fileName: entry.name,
                lineNumber: i + 1,
                snippet: lines.slice(start, end).join('\n').substring(0, 200),
              });
              break; // one hit per file
            }
          }
        }
      }
    }
  }

  return { ok: true, results };
});
```

- [ ] **Step 2: 在 preload.cjs 暴露**

```javascript
grepWorkspace: (pattern, libraryId) => ipcRenderer.invoke("grep-workspace", pattern, libraryId),
```

- [ ] **Step 3: 创建 BacklinksPanel.tsx**

```typescript
import { useState, useEffect } from 'react';
import { ExternalLink } from 'lucide-react';
import type { BacklinkEntry } from './types';

interface BacklinksPanelProps {
  paperId: string;
  libraryId: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function BacklinksPanel({ paperId, libraryId, isOpen, onToggle }: BacklinksPanelProps) {
  const [entries, setEntries] = useState<BacklinkEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen || !paperId) return;
    const shell = window.desktopShell;
    if (!shell || shell.runtime !== 'electron') return;

    setLoading(true);
    const pattern = `[[@${paperId}]]`;
    shell.grepWorkspace(pattern, libraryId).then((r: any) => {
      if (r?.ok) setEntries(r.results || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [isOpen, paperId, libraryId]);

  if (!isOpen) return null;

  return (
    <div className="w-64 shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-on-surface-variant">Backlinks ({entries.length})</h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>

        {loading && <p className="text-xs text-outline">Searching...</p>}

        {!loading && entries.length === 0 && (
          <p className="text-xs text-outline">No backlinks found</p>
        )}

        {entries.map((entry, i) => (
          <div key={i} className="mb-2 p-2 rounded bg-surface-container text-xs">
            <div className="flex items-center gap-1 mb-0.5">
              <span className="text-on-surface font-mono truncate" title={entry.fileName}>
                {entry.fileName}
              </span>
              <span className="text-outline">:{entry.lineNumber}</span>
              <button
                className="ml-auto text-outline hover:text-primary"
                onClick={() => {
                  // Open this file in a new tab
                  window.dispatchEvent(new CustomEvent('open-reader-file', {
                    detail: { path: entry.filePath },
                  }));
                }}
              >
                <ExternalLink className="w-3 h-3" />
              </button>
            </div>
            <pre className="text-[10px] text-on-surface-variant mt-0.5 whitespace-pre-wrap break-all">
              {entry.snippet}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 在 ViewerHost 中集成反链面板**

在 ViewerHost 的渲染区域，`AnnotationSidebar` 旁边或后面添加：

```typescript
<BacklinksPanel
  paperId={paperId}
  libraryId={libraryId}
  isOpen={backlinksOpen}
  onToggle={() => setBacklinksOpen(!backlinksOpen)}
/>
```

同时添加 `backlinksOpen` 状态和切换按钮。

- [ ] **Step 5: 提交**

```bash
git add electron/main.cjs electron/preload.cjs \
  scholarai-workbench/src/components/reader/BacklinksPanel.tsx \
  scholarai-workbench/src/components/reader/ViewerHost.tsx
git commit -m "feat: add backlinks panel — grep workspace .md files for [[@paperId]]"
```

---

### Task 8: 相关实体面板

**Files:**
- Create: `src/components/reader/RelatedEntities.tsx`
- Modify: `src/components/reader/ViewerHost.tsx` — 加面板入口

- [ ] **Step 1: 创建 RelatedEntities.tsx**

```typescript
import { useState, useEffect } from 'react';
import { Link2, Variable, GitBranch } from 'lucide-react';
import type { GraphNode, GraphEdge, PaperDetail } from '../../types';

interface RelatedEntitiesProps {
  paperId: string;
  libraryId: string;
  graphData: { nodes: GraphNode[]; edges: GraphEdge[]; paper_map: Record<string, PaperDetail> } | null;
  isOpen: boolean;
  onToggle: () => void;
}

export default function RelatedEntities({ paperId, libraryId, graphData, isOpen, onToggle }: RelatedEntitiesProps) {
  if (!isOpen) return null;

  // Find entities linked to this paper
  const paperNodes: GraphNode[] = [];
  const paperEdges: GraphEdge[] = [];

  if (graphData) {
    const scopedKey = `${libraryId}::${paperId}`;
    const paper = graphData.paper_map?.[scopedKey] || graphData.paper_map?.[paperId];
    const variableNames = new Set<string>(
      (paper?.context_variables || []).concat(
        (paper?.main_effects || []).flatMap(e => [e.from, e.to])
      )
    );

    for (const node of graphData.nodes) {
      if (node.type === 'variable' && variableNames.has(node.id)) {
        paperNodes.push(node);
      }
    }

    paperEdges.push(...graphData.edges.filter(
      e => variableNames.has(typeof e.source === 'string' ? e.source : e.source?.id || '')
           && variableNames.has(typeof e.target === 'string' ? e.target : e.target?.id || '')
    ));
  }

  return (
    <div className="w-60 shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-on-surface-variant">
            Related Entities ({paperNodes.length} nodes, {paperEdges.length} edges)
          </h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>

        {paperNodes.length === 0 && paperEdges.length === 0 && (
          <p className="text-xs text-outline">No extracted entities for this paper</p>
        )}

        {paperNodes.length > 0 && (
          <div className="mb-3">
            <h5 className="text-[10px] font-medium text-outline mb-1 flex items-center gap-1">
              <Variable className="w-3 h-3" /> Variables
            </h5>
            {paperNodes.map(node => (
              <button
                key={node.id}
                className="block w-full text-left text-xs px-1.5 py-0.5 rounded truncate hover:bg-surface-container-low text-on-surface-variant"
                onClick={() => {
                  window.dispatchEvent(new CustomEvent('navigate-to-node', { detail: { nodeId: node.id } }));
                }}
              >
                {node.label || node.name || node.id}
              </button>
            ))}
          </div>
        )}

        {paperEdges.length > 0 && (
          <div>
            <h5 className="text-[10px] font-medium text-outline mb-1 flex items-center gap-1">
              <GitBranch className="w-3 h-3" /> Effects
            </h5>
            {paperEdges.map((edge, i) => {
              const src = typeof edge.source === 'string' ? edge.source : edge.source?.id || '?';
              const tgt = typeof edge.target === 'string' ? edge.target : edge.target?.id || '?';
              return (
                <div key={i} className="text-[10px] text-on-surface-variant px-1.5 py-0.5 truncate">
                  {src} → {tgt}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 在 ViewerHost 集成相关实体面板**

```typescript
// 在 ViewerHost 中添加:
const [entitiesOpen, setEntitiesOpen] = useState(false);
const { graphData } = useApp();

// 在面板区域:
<RelatedEntities
  paperId={paperId}
  libraryId={libraryId}
  graphData={graphData}
  isOpen={entitiesOpen}
  onToggle={() => setEntitiesOpen(!entitiesOpen)}
/>
```

- [ ] **Step 3: 提交**

```bash
git add scholarai-workbench/src/components/reader/RelatedEntities.tsx \
  scholarai-workbench/src/components/reader/ViewerHost.tsx
git commit -m "feat: add related entities panel showing KG nodes/edges for current paper"
```

---

## 不做的部分

- 文件浏览器（LibraryView 已覆盖）
- 主题系统（Tailwind theme 足够）
- 插件系统
- 跨文件全文搜索（已有 RAG 搜索替代）
- Pop-out 窗口
- Daily notes / 日记 / 幻灯片 / 白板
