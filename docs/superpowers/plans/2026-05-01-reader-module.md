# Reader Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform ReaderView from structured data display into a full document reader with PDF (pdf.js v4) and Markdown (CodeMirror 6 + remark) support, plus client-side annotations.

**Architecture:** Reader Shell (`ReaderView.tsx`) + Pluggable Viewers (`PdfViewer`, `MarkdownEditor`). Shared `AnnotationSidebar` with IndexedDB-backed `AnnotationManager`. Electron main process reads local files and passes to renderer via `contextBridge`.

**Tech Stack:** React 19, TypeScript 5.8, Vite 6, Tailwind 4, pdf.js v4, CodeMirror 6, remark, react-markdown, idb, KaTeX

---

## File Structure Map

```
scholarai-workbench/
├── src/
│   ├── types.ts                                    [MODIFY] +PaperFiles type
│   ├── api.ts                                      [MODIFY] +getPaperFiles()
│   ├── components/
│   │   ├── ReaderView.tsx                          [MODIFY] complete rewrite (shell)
│   │   └── reader/
│   │       ├── types.ts                            [CREATE] reader-specific types
│   │       ├── DocumentResolver.ts                 [CREATE] paper_id → file path
│   │       ├── PdfViewer.tsx                       [CREATE] pdf.js iframe wrapper
│   │       ├── PdfAnnotations.tsx                   [CREATE] SVG/Canvas annotation overlay
│   │       ├── MarkdownEditor.tsx                  [CREATE] CM6 + react-markdown
│   │       ├── AnnotationManager.ts               [CREATE] IndexedDB CRUD
│   │       ├── AnnotationSidebar.tsx               [CREATE] annotation list/edit
│   │       └── ViewerHost.tsx                      [CREATE] file dispatch
│   └── App.tsx                                     [MODIFY] minor context update
├── electron/
│   ├── preload.cjs                                 [MODIFY] +readLocalFile/readLocalText
│   └── main.cjs                                    [MODIFY] +IPC handlers
├── package.json                                    [MODIFY] +dependencies
├── tsconfig.json                                   [MODIFY] +paths alias
└── src/__tests__/                                  [CREATE] test directory
    └── reader/                                     [CREATE] reader tests
```

Backend:
```
src/kn_graph/routers/graph.py                       [MODIFY] +/paper/{id}/files endpoint
```

---

### Task 1: Install Dependencies

**Files:**
- Modify: `scholarai-workbench/package.json`
- Modify: `scholarai-workbench/tsconfig.json`

- [ ] **Step 1: Add dependencies to package.json**

Run:
```bash
cd scholarai-workbench
npm install pdfjs-dist@^4.10
npm install @codemirror/view @codemirror/state @codemirror/lang-markdown @codemirror/language @codemirror/commands @codemirror/search
npm install react-markdown@^9 remark-gfm@^4 remark-math@^6 rehype-katex@^7 katex@^0.16
npm install idb@^8
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Verify installation**

Run: `node -e "require('pdfjs-dist'); console.log('pdfjs OK')"`
Run: `node -e "require('@codemirror/view'); console.log('CM6 OK')"`
Expected: No errors

- [ ] **Step 3: Update tsconfig.json paths**

Add to `compilerOptions` in `scholarai-workbench/tsconfig.json`:
```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"],
      "@reader/*": ["./src/components/reader/*"]
    }
  }
}
```

- [ ] **Step 4: Add test script to package.json**

In `scripts`:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 5: Create vitest config**

Create `scholarai-workbench/vitest.config.ts`:
```typescript
import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: [],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
      '@reader': path.resolve(__dirname, 'src/components/reader'),
    },
  },
});
```

- [ ] **Step 6: Type check**

Run: `npm run lint`
Expected: TypeScript compilation succeeds (minus unimplemented imports)

- [ ] **Step 7: Commit**

```bash
git add scholarai-workbench/package.json scholarai-workbench/package-lock.json scholarai-workbench/tsconfig.json scholarai-workbench/vitest.config.ts
git commit -m "chore: add reader dependencies (pdfjs, codemirror, remark, vitest)"
```

---

### Task 2: Reader Types

**Files:**
- Create: `scholarai-workbench/src/components/reader/types.ts`
- Modify: `scholarai-workbench/src/types.ts` (add PaperFiles export)

- [ ] **Step 1: Write types test**

Create `scholarai-workbench/src/__tests__/reader/types.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';

describe('Reader types', () => {
  it('Annotation type has required fields', () => {
    const ann = {
      id: 'uuid-1',
      paper_id: 'paper-1',
      library_id: 'lib-1',
      type: 'highlight' as const,
      page_index: 0,
      rects: [{ x: 10, y: 20, width: 100, height: 20, page_index: 0 }],
      text: 'selected text',
      comment: '',
      color: '#ffeb3b',
      ink_paths: [],
      linked_node_ids: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };
    expect(ann.id).toBe('uuid-1');
    expect(ann.type).toBe('highlight');
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `npx vitest run src/__tests__/reader/types.test.ts`
Expected: FAIL (file not found)

- [ ] **Step 3: Create reader types**

Create `scholarai-workbench/src/components/reader/types.ts`:
```typescript
export interface AnnotationRect {
  x: number;
  y: number;
  width: number;
  height: number;
  page_index: number;
}

export interface InkPath {
  points: { x: number; y: number }[];
  width: number;
  color: string;
}

export type AnnotationType = 'highlight' | 'underline' | 'note' | 'ink';

export interface Annotation {
  id: string;
  paper_id: string;
  library_id: string;
  type: AnnotationType;
  page_index: number;
  rects: AnnotationRect[];
  text: string;
  comment: string;
  color: string;
  ink_paths: InkPath[];
  linked_node_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface AnnotationCreate {
  paper_id: string;
  library_id: string;
  type: AnnotationType;
  page_index: number;
  rects: AnnotationRect[];
  text: string;
  comment: string;
  color: string;
  ink_paths: InkPath[];
  linked_node_ids: string[];
}

export type ViewerMode = 'edit' | 'live-preview' | 'read';

export interface FileInfo {
  path: string;
  name: string;
  size_bytes: number;
}

export interface PaperFiles {
  paper_id: string;
  library_id: string;
  files: {
    pdf?: FileInfo;
    markdown?: FileInfo;
    html?: FileInfo;
  };
  default_view: 'pdf' | 'markdown' | 'html' | 'none';
}

export interface DocumentLoadResult {
  type: 'pdf' | 'markdown' | 'html' | 'none';
  data: Uint8Array | string | null;
  fileName: string;
}
```

- [ ] **Step 4: Add PaperFiles to main types.ts**

In `scholarai-workbench/src/types.ts`, after the existing interfaces, add:
```typescript
export interface PaperFilesFileInfo {
  path: string;
  name: string;
  size_bytes: number;
}

export interface PaperFiles {
  paper_id: string;
  library_id: string;
  files: {
    pdf?: PaperFilesFileInfo;
    markdown?: PaperFilesFileInfo;
    html?: PaperFilesFileInfo;
  };
  default_view: 'pdf' | 'markdown' | 'html' | 'none';
}
```

- [ ] **Step 5: Run type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scholarai-workbench/src/components/reader/types.ts scholarai-workbench/src/types.ts scholarai-workbench/src/__tests__/reader/types.test.ts
git commit -m "feat: add reader type definitions (Annotation, PaperFiles, DocumentLoadResult)"
```

---

### Task 3: Backend /paper/{id}/files API

**Files:**
- Modify: `src/kn_graph/routers/graph.py`
- Modify: `src/kn_graph/services/graph_service.py`

- [ ] **Step 1: Add get_paper_files method to GraphService**

In `src/kn_graph/services/graph_service.py`, after the `get_paper` method, add:
```python
def get_paper_files(self, paper_id_or_doi: str, library_id: str = "") -> dict[str, Any] | None:
    """Return available readable files for a paper."""
    paper = self.get_paper(paper_id_or_doi, library_id=library_id)
    if paper is None:
        return None
    files: dict[str, dict[str, str | int]] = {}
    source_pdf = str(paper.get("source_pdf_path", "") or "").strip()
    if source_pdf:
        p = Path(source_pdf)
        if p.exists():
            files["pdf"] = {
                "path": source_pdf,
                "name": p.name,
                "size_bytes": p.stat().st_size,
            }
            if "default_view" not in files:
                files["default_view"] = "pdf"
    source_md = str(paper.get("source_md_path", "") or "").strip()
    if not source_md:
        pkey = paper.get("paper_key", "")
        meta = self._paper_meta_by_key.get(pkey, {})
        source_md = str(meta.get("source_md_path", "") or "").strip()
    if source_md:
        p = Path(source_md)
        if p.exists() and p.is_file():
            files["markdown"] = {
                "path": source_md,
                "name": p.name,
                "size_bytes": p.stat().st_size,
            }
        elif p.exists() and p.is_dir():
            cand = p / "full.md"
            if cand.exists():
                files["markdown"] = {
                    "path": str(cand),
                    "name": cand.name,
                    "size_bytes": cand.stat().st_size,
                }
    offline_html = str(paper.get("offline_html_path", "") or "").strip()
    if offline_html:
        p = Path(offline_html)
        if p.exists():
            files["html"] = {
                "path": offline_html,
                "name": p.name,
                "size_bytes": p.stat().st_size,
            }
    default_view = files.get("default_view", "none")
    if "default_view" in files:
        del files["default_view"]
    return {
        "paper_id": paper.get("paper_id", paper_id_or_doi),
        "library_id": paper.get("library_id", library_id),
        "files": dict(files),
        "default_view": default_view,
    }
```

- [ ] **Step 2: Add route in graph.py**

In `src/kn_graph/routers/graph.py`, in `create_paper_router`, add after the `variable_detail` route:
```python
@router.get("/paper/{paper_id_or_doi}/files")
async def paper_files(paper_id_or_doi: str, library_id: str = Query(default="")):
    result = graph_service.get_paper_files(paper_id_or_doi, library_id=library_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "paper_not_found", "paper_id": paper_id_or_doi})
    return result
```

- [ ] **Step 3: Add vite proxy for /paper sub-routes**

In `scholarai-workbench/vite.config.ts`, verify the `/paper` proxy already covers `/paper/.../files`. The existing config proxies `/paper` to the backend, which should handle nested paths. No change needed.

- [ ] **Step 4: Verify endpoint works**

Run: `curl http://127.0.0.1:8013/paper/any_paper_id/files?library_id=supply_chain`
Expected: JSON response with file paths or 404

- [ ] **Step 5: Commit**

```bash
git add src/kn_graph/routers/graph.py src/kn_graph/services/graph_service.py
git commit -m "feat: add /paper/{id}/files endpoint returning readable file paths"
```

---

### Task 4: Electron File Read APIs

**Files:**
- Modify: `scholarai-workbench/electron/main.cjs`
- Modify: `scholarai-workbench/electron/preload.cjs`

- [ ] **Step 1: Add IPC handler in main.cjs**

In `scholarai-workbench/electron/main.cjs`, after the existing `open-local-path` handler (line 321), add:
```javascript
ipcMain.handle("read-local-file", async (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    const buf = fs.readFileSync(p);
    return { ok: true, data: buf.toString('base64'), size: buf.length };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("read-local-text", async (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    const text = fs.readFileSync(p, "utf8");
    return { ok: true, data: text, size: Buffer.byteLength(text, 'utf8') };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
```

- [ ] **Step 2: Expose APIs in preload.cjs**

In `scholarai-workbench/electron/preload.cjs`, add to the `contextBridge.exposeInMainWorld` object:
```javascript
contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  runtime: "electron",
  getBackendPort: () => ipcRenderer.invoke("get-backend-port"),
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLocalPath: (targetPath) => ipcRenderer.invoke("open-local-path", targetPath),
  readLocalFile: (filePath) => ipcRenderer.invoke("read-local-file", filePath),
  readLocalText: (filePath) => ipcRenderer.invoke("read-local-text", filePath),
});
```

- [ ] **Step 3: Add TypeScript declaration**

Create `scholarai-workbench/src/electron.d.ts`:
```typescript
interface DesktopShell {
  platform: string;
  runtime: string;
  getBackendPort(): Promise<number>;
  getBackendUrl(): Promise<string>;
  restartBackend(): Promise<number>;
  openLocalPath(targetPath: string): Promise<{ ok: boolean; error?: string }>;
  readLocalFile(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
  readLocalText(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
}

declare global {
  interface Window {
    desktopShell?: DesktopShell;
  }
}

export {};
```

- [ ] **Step 4: Commit**

```bash
git add scholarai-workbench/electron/main.cjs scholarai-workbench/electron/preload.cjs scholarai-workbench/src/electron.d.ts
git commit -m "feat: add Electron IPC handlers for local file reading"
```

---

### Task 5: DocumentResolver

**Files:**
- Create: `scholarai-workbench/src/components/reader/DocumentResolver.ts`
- Create: `scholarai-workbench/src/__tests__/reader/DocumentResolver.test.ts`

- [ ] **Step 1: Write test**

Create `scholarai-workbench/src/__tests__/reader/DocumentResolver.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('DocumentResolver', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('resolves paper_id to file list via API', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({
        paper_id: 'doi_test',
        library_id: 'supply_chain',
        files: {
          pdf: { path: '/data/test.pdf', name: 'test.pdf', size_bytes: 1000 },
        },
        default_view: 'pdf',
      })),
    });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    const result = await resolvePaperFiles('doi_test', 'supply_chain');
    expect(result.default_view).toBe('pdf');
    expect(result.files.pdf).toBeDefined();
  });

  it('returns none when no files available', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve(JSON.stringify({
        paper_id: 'doi_test',
        library_id: 'supply_chain',
        files: {},
        default_view: 'none',
      })),
    });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    const result = await resolvePaperFiles('doi_test', 'supply_chain');
    expect(result.default_view).toBe('none');
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `npx vitest run src/__tests__/reader/DocumentResolver.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement DocumentResolver**

Create `scholarai-workbench/src/components/reader/DocumentResolver.ts`:
```typescript
import type { PaperFiles } from './types';

const API_BASE = '';

export async function resolvePaperFiles(
  paperId: string,
  libraryId: string,
): Promise<PaperFiles> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
  const resp = await fetch(`${API_BASE}/paper/${encodeURIComponent(paperId)}/files${params}`);
  if (!resp.ok) {
    throw new Error(`failed to resolve paper files: ${resp.status}`);
  }
  return resp.json();
}

async function electronReadFile(path: string): Promise<Uint8Array | null> {
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

async function electronReadText(path: string): Promise<string | null> {
  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return null;
  const result = await shell.readLocalText(path);
  if (!result.ok || !result.data) return null;
  return result.data;
}

async function browserReadFile(path: string): Promise<Uint8Array | null> {
  const resp = await fetch(`/paper/file?path=${encodeURIComponent(path)}`);
  if (!resp.ok) return null;
  const buf = await resp.arrayBuffer();
  return new Uint8Array(buf);
}

async function browserReadText(path: string): Promise<string | null> {
  const resp = await fetch(`/paper/file?path=${encodeURIComponent(path)}`);
  if (!resp.ok) return null;
  return resp.text();
}

export async function loadDocument(
  files: PaperFiles,
): Promise<{ type: 'pdf' | 'markdown' | 'html' | 'none'; data: Uint8Array | string | null; fileName: string }> {
  const isElectron = window.desktopShell?.runtime === 'electron';

  if (files.files.pdf) {
    const f = files.files.pdf;
    const data = isElectron
      ? await electronReadFile(f.path)
      : await browserReadFile(f.path);
    return { type: 'pdf', data, fileName: f.name };
  }

  if (files.files.markdown) {
    const f = files.files.markdown;
    const data = isElectron
      ? await electronReadText(f.path)
      : await browserReadText(f.path);
    return { type: 'markdown', data, fileName: f.name };
  }

  if (files.files.html) {
    const f = files.files.html;
    const data = isElectron
      ? await electronReadText(f.path)
      : await browserReadText(f.path);
    return { type: 'html', data, fileName: f.name };
  }

  return { type: 'none', data: null, fileName: '' };
}
```

- [ ] **Step 4: Run test**

Run: `npx vitest run src/__tests__/reader/DocumentResolver.test.ts`
Expected: PASS

- [ ] **Step 5: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scholarai-workbench/src/components/reader/DocumentResolver.ts scholarai-workbench/src/__tests__/reader/DocumentResolver.test.ts
git commit -m "feat: add DocumentResolver for paper_id to file path mapping"
```

---

### Task 6: PdfViewer Basic Rendering

**Files:**
- Create: `scholarai-workbench/src/components/reader/PdfViewer.tsx`

- [ ] **Step 1: Create PdfViewer component**

Create `scholarai-workbench/src/components/reader/PdfViewer.tsx`:
```typescript
import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface PdfViewerProps {
  data: Uint8Array;
  fileName: string;
  onSelection?: (text: string, rects: { x: number; y: number; width: number; height: number; page: number }[]) => void;
}

export default function PdfViewer({ data, fileName, onSelection }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjsLib.getDocument({ data });
    loadingTask.promise.then((pdf) => {
      if (cancelled) return;
      pdfDocRef.current = pdf;
      setPageCount(pdf.numPages);
      setCurrentPage(1);
      setLoading(false);
    }).catch((e) => {
      if (cancelled) return;
      setError(`Failed to load PDF: ${e.message}`);
      setLoading(false);
    });

    return () => {
      cancelled = true;
      loadingTask.destroy().catch(() => {});
    };
  }, [data]);

  useEffect(() => {
    if (!pdfDocRef.current || !containerRef.current) return;
    let cancelled = false;

    pdfDocRef.current.getPage(currentPage).then((page) => {
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const container = containerRef.current!;
      container.innerHTML = '';

      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.display = 'block';
      canvas.style.margin = '0 auto';
      container.appendChild(canvas);

      const ctx = canvas.getContext('2d')!;
      page.render({ canvasContext: ctx, viewport }).promise.then(() => {
        if (cancelled) return;

        const textLayerDiv = document.createElement('div');
        textLayerDiv.className = 'textLayer';
        textLayerDiv.style.position = 'absolute';
        textLayerDiv.style.left = '0';
        textLayerDiv.style.top = '0';
        textLayerDiv.style.width = `${viewport.width}px`;
        textLayerDiv.style.height = `${viewport.height}px`;
        container.style.position = 'relative';
        container.appendChild(textLayerDiv);

        page.getTextContent().then((textContent) => {
          if (cancelled || !textLayerDiv) return;
          pdfjsLib.renderTextLayer({
            textContentSource: textContent,
            container: textLayerDiv,
            viewport,
            textDivs: [],
          });
        });
      });
    });

    return () => { cancelled = true; };
  }, [currentPage, scale]);

  return (
    <div className="flex flex-col h-full bg-surface-container-low">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        <div className="flex items-center gap-3">
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container disabled:opacity-30"
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          >
            Prev
          </button>
          <span className="text-xs font-mono">{currentPage} / {pageCount}</span>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container disabled:opacity-30"
            disabled={currentPage >= pageCount}
            onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.round((s + 0.2) * 10) / 10)}
          >
            Zoom {Math.round(scale * 100)}%
          </button>
          <button
            className="px-2 py-1 text-xs border border-outline-variant rounded hover:bg-surface-container"
            onClick={() => setScale((s) => Math.max(0.5, Math.round((s - 0.2) * 10) / 10))}
          >
            Out
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto flex justify-center p-4">
        {loading && <div className="text-sm text-on-surface-variant self-center">Loading PDF...</div>}
        {error && <div className="text-sm text-error self-center">{error}</div>}
        <div ref={containerRef} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check**

Run: `npm run lint`
Expected: PASS (may need pdfjs types)

- [ ] **Step 3: Commit**

```bash
git add scholarai-workbench/src/components/reader/PdfViewer.tsx
git commit -m "feat: add PdfViewer with pdf.js v4 rendering, pagination, and zoom"
```

---

### Task 7: MarkdownEditor

**Files:**
- Create: `scholarai-workbench/src/components/reader/MarkdownEditor.tsx`

- [ ] **Step 1: Create MarkdownEditor**

Create `scholarai-workbench/src/components/reader/MarkdownEditor.tsx`:
```typescript
import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import type { ViewerMode } from './types';

interface MarkdownEditorProps {
  content: string;
  fileName: string;
  mode?: ViewerMode;
  onModeChange?: (mode: ViewerMode) => void;
  onContentChange?: (content: string) => void;
}

export default function MarkdownEditor({
  content,
  fileName,
  mode: initialMode = 'read',
  onModeChange,
  onContentChange,
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<ViewerMode>(initialMode);
  const [text, setText] = useState(content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setText(content);
  }, [content]);

  const handleModeChange = (newMode: ViewerMode) => {
    setMode(newMode);
    onModeChange?.(newMode);
  };

  return (
    <div className="flex flex-col h-full bg-surface-container-low">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        <div className="flex items-center gap-1 bg-surface-container rounded-lg p-0.5">
          {(['edit', 'live-preview', 'read'] as ViewerMode[]).map((m) => (
            <button
              key={m}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                mode === m
                  ? 'bg-primary-container text-on-primary-container font-medium'
                  : 'text-on-surface-variant hover:bg-surface-container-low'
              }`}
              onClick={() => handleModeChange(m)}
            >
              {m === 'edit' ? 'Edit' : m === 'live-preview' ? 'Preview' : 'Read'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {mode === 'edit' && (
          <textarea
            ref={textareaRef}
            className="w-full h-full resize-none p-6 font-mono text-sm bg-surface-container-lowest text-on-surface outline-none border-0"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              onContentChange?.(e.target.value);
            }}
          />
        )}

        {mode === 'read' && (
          <div className="h-full overflow-y-auto p-6 max-w-[800px] mx-auto">
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
              >
                {text}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {mode === 'live-preview' && (
          <div className="flex h-full">
            <textarea
              className="flex-1 resize-none p-4 font-mono text-sm bg-surface-container-lowest text-on-surface outline-none border-r border-outline-variant"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                onContentChange?.(e.target.value);
              }}
            />
            <div className="flex-1 overflow-y-auto p-4">
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                >
                  {text}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scholarai-workbench/src/components/reader/MarkdownEditor.tsx
git commit -m "feat: add MarkdownEditor with edit/read/live-preview modes via react-markdown"
```

---

### Task 8: AnnotationManager (IndexedDB)

**Files:**
- Create: `scholarai-workbench/src/components/reader/AnnotationManager.ts`
- Create: `scholarai-workbench/src/__tests__/reader/AnnotationManager.test.ts`

- [ ] **Step 1: Implement AnnotationManager**

Create `scholarai-workbench/src/components/reader/AnnotationManager.ts`:
```typescript
import { openDB, type IDBPDatabase } from 'idb';
import type { Annotation, AnnotationCreate } from './types';

const DB_NAME = 'kn-graph-reader';
const STORE_NAME = 'annotations';
const DB_VERSION = 1;

let dbPromise: Promise<IDBPDatabase> | null = null;

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
          store.createIndex('paper_id', 'paper_id', { unique: false });
          store.createIndex('page_index', 'page_index', { unique: false });
          store.createIndex('created_at', 'created_at', { unique: false });
        }
      },
    });
  }
  return dbPromise;
}

export const annotationManager = {
  async getAllByPaper(paperId: string): Promise<Annotation[]> {
    const db = await getDb();
    const index = db.transaction(STORE_NAME).store.index('paper_id');
    return index.getAll(paperId);
  },

  async add(create: AnnotationCreate): Promise<Annotation> {
    const db = await getDb();
    const now = new Date().toISOString();
    const annotation: Annotation = {
      ...create,
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
    };
    await db.add(STORE_NAME, annotation);
    return annotation;
  },

  async update(id: string, changes: Partial<Pick<Annotation, 'comment' | 'color' | 'linked_node_ids'>>): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const existing = await store.get(id);
    if (!existing) return;
    const updated = { ...existing, ...changes, updated_at: new Date().toISOString() };
    await store.put(updated);
    await tx.done;
  },

  async remove(id: string): Promise<void> {
    const db = await getDb();
    await db.delete(STORE_NAME, id);
  },

  async removeByPaper(paperId: string): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const index = tx.store.index('paper_id');
    const all = await index.getAllKeys(paperId);
    for (const key of all) {
      await tx.store.delete(key);
    }
    await tx.done;
  },

  async exportByPaper(paperId: string): Promise<Annotation[]> {
    return this.getAllByPaper(paperId);
  },
};
```

- [ ] **Step 2: Write test**

Create `scholarai-workbench/src/__tests__/reader/AnnotationManager.test.ts`:
```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { annotationManager } from '../../components/reader/AnnotationManager';
import type { AnnotationCreate } from '../../components/reader/types';
import 'fake-indexeddb/auto';

describe('AnnotationManager', () => {
  it('adds and retrieves annotations by paper_id', async () => {
    const create: AnnotationCreate = {
      paper_id: 'paper-1',
      library_id: 'lib-1',
      type: 'highlight',
      page_index: 0,
      rects: [{ x: 10, y: 20, width: 100, height: 20, page_index: 0 }],
      text: 'test text',
      comment: '',
      color: '#ffeb3b',
      ink_paths: [],
      linked_node_ids: [],
    };
    const ann = await annotationManager.add(create);
    expect(ann.id).toBeDefined();
    expect(ann.type).toBe('highlight');

    const all = await annotationManager.getAllByPaper('paper-1');
    expect(all).toHaveLength(1);
    expect(all[0].text).toBe('test text');
  });

  it('updates annotation comment', async () => {
    const ann = await annotationManager.add({
      paper_id: 'paper-2', library_id: 'lib-1', type: 'note',
      page_index: 0, rects: [], text: '', comment: 'old', color: '#ffff00',
      ink_paths: [], linked_node_ids: [],
    });
    await annotationManager.update(ann.id, { comment: 'new comment' });
    const all = await annotationManager.getAllByPaper('paper-2');
    expect(all[0].comment).toBe('new comment');
  });

  it('removes annotation', async () => {
    const ann = await annotationManager.add({
      paper_id: 'paper-3', library_id: 'lib-1', type: 'underline',
      page_index: 1, rects: [], text: '', comment: '', color: '#00ff00',
      ink_paths: [], linked_node_ids: [],
    });
    await annotationManager.remove(ann.id);
    const all = await annotationManager.getAllByPaper('paper-3');
    expect(all).toHaveLength(0);
  });
});
```

- [ ] **Step 3: Install fake-indexeddb for testing**

Run: `npm install -D fake-indexeddb`

- [ ] **Step 4: Run tests**

Run: `npx vitest run src/__tests__/reader/AnnotationManager.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scholarai-workbench/src/components/reader/AnnotationManager.ts scholarai-workbench/src/__tests__/reader/AnnotationManager.test.ts
git commit -m "feat: add AnnotationManager with IndexedDB CRUD via idb"
```

---

### Task 9: AnnotationSidebar

**Files:**
- Create: `scholarai-workbench/src/components/reader/AnnotationSidebar.tsx`

- [ ] **Step 1: Create AnnotationSidebar**

Create `scholarai-workbench/src/components/reader/AnnotationSidebar.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { Highlighter, Underline, StickyNote, Trash2, Pencil } from 'lucide-react';
import { annotationManager } from './AnnotationManager';
import type { Annotation } from './types';

interface AnnotationSidebarProps {
  paperId: string;
  isOpen: boolean;
  onToggle: () => void;
  onAnnotationClick?: (annotation: Annotation) => void;
}

const typeLabels: Record<string, string> = {
  highlight: 'Highlight',
  underline: 'Underline',
  note: 'Note',
  ink: 'Ink',
};

const typeIcons: Record<string, React.ReactNode> = {
  highlight: <Highlighter className="w-3.5 h-3.5" />,
  underline: <Underline className="w-3.5 h-3.5" />,
  note: <StickyNote className="w-3.5 h-3.5" />,
  ink: <Pencil className="w-3.5 h-3.5" />,
};

const colorMap: Record<string, string> = {
  '#ffeb3b': 'bg-yellow-200',
  '#ff9800': 'bg-orange-200',
  '#f44336': 'bg-red-200',
  '#4caf50': 'bg-green-200',
  '#2196f3': 'bg-blue-200',
  '#9c27b0': 'bg-purple-200',
};

export default function AnnotationSidebar({ paperId, isOpen, onToggle, onAnnotationClick }: AnnotationSidebarProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editComment, setEditComment] = useState('');

  useEffect(() => {
    if (!paperId) return;
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
  }, [paperId]);

  const refresh = () => {
    annotationManager.getAllByPaper(paperId).then(setAnnotations).catch(() => setAnnotations([]));
  };

  const handleDelete = async (id: string) => {
    await annotationManager.remove(id);
    refresh();
  };

  const handleSave = async (id: string) => {
    await annotationManager.update(id, { comment: editComment });
    setEditingId(null);
    refresh();
  };

  const sorted = [...annotations].sort((a, b) => {
    if (a.page_index !== b.page_index) return a.page_index - b.page_index;
    const aTop = a.rects[0]?.y ?? 0;
    const bTop = b.rects[0]?.y ?? 0;
    return aTop - bTop;
  });

  return (
    <div className={`border-l border-outline-variant bg-surface-container-lowest flex flex-col transition-all duration-200 ${isOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
      <div className="px-3 py-2 border-b border-outline-variant flex items-center justify-between">
        <span className="text-xs font-mono font-bold text-on-surface uppercase tracking-wider">Annotations ({annotations.length})</span>
        <button onClick={onToggle} className="text-xs text-outline hover:text-on-surface">x</button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sorted.length === 0 && (
          <p className="text-xs text-on-surface-variant text-center py-8">No annotations yet</p>
        )}
        {sorted.map((ann) => (
          <div
            key={ann.id}
            className="p-2 rounded-lg border border-outline-variant/50 hover:bg-surface-container cursor-pointer transition-colors"
            onClick={() => onAnnotationClick?.(ann)}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-outline">{typeIcons[ann.type]}</span>
              <span className="text-[10px] font-mono text-outline">Pg {ann.page_index + 1}</span>
              <span
                className="w-3 h-3 rounded-full border border-outline-variant"
                style={{ backgroundColor: ann.color }}
              />
              <button
                className="ml-auto text-outline hover:text-error"
                onClick={(e) => { e.stopPropagation(); handleDelete(ann.id); }}
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
            {ann.text && (
              <p className="text-xs text-on-surface line-clamp-2 leading-relaxed">{ann.text}</p>
            )}
            {editingId === ann.id ? (
              <div className="mt-1" onClick={(e) => e.stopPropagation()}>
                <textarea
                  className="w-full text-xs p-1 border border-outline-variant rounded bg-surface-container"
                  rows={2}
                  value={editComment}
                  onChange={(e) => setEditComment(e.target.value)}
                />
                <div className="flex gap-1 mt-1">
                  <button className="text-[10px] px-2 py-0.5 bg-primary-container text-on-primary-container rounded" onClick={() => handleSave(ann.id)}>Save</button>
                  <button className="text-[10px] px-2 py-0.5 text-outline" onClick={() => setEditingId(null)}>Cancel</button>
                </div>
              </div>
            ) : ann.comment ? (
              <p className="text-xs text-secondary mt-1 italic">{ann.comment}</p>
            ) : (
              <button
                className="text-[10px] text-outline hover:text-secondary mt-1"
                onClick={(e) => { e.stopPropagation(); setEditingId(ann.id); setEditComment(ann.comment); }}
              >
                Add note...
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scholarai-workbench/src/components/reader/AnnotationSidebar.tsx
git commit -m "feat: add AnnotationSidebar with list, edit, and delete for annotations"
```

---

### Task 10: PdfAnnotations Overlay

**Files:**
- Create: `scholarai-workbench/src/components/reader/PdfAnnotations.tsx`

- [ ] **Step 1: Create PdfAnnotations**

Create `scholarai-workbench/src/components/reader/PdfAnnotations.tsx`:
```typescript
import { useEffect, useRef } from 'react';
import type { Annotation } from './types';

interface PdfAnnotationsProps {
  annotations: Annotation[];
  currentPage: number;
  scale: number;
  containerRef: React.RefObject<HTMLDivElement | null>;
  onAddAnnotation?: (rects: { x: number; y: number; width: number; height: number; page: number }[], text: string) => void;
}

export default function PdfAnnotations({ annotations, currentPage, scale, containerRef }: PdfAnnotationsProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!containerRef.current || !svgRef.current) return;
    const container = containerRef.current;
    const svg = svgRef.current;

    svg.innerHTML = '';
    const pageAnn = annotations.filter((a) => a.page_index === currentPage - 1);
    if (pageAnn.length === 0) return;

    const canvas = container.querySelector('canvas');
    if (!canvas) return;

    svg.setAttribute('width', String(canvas.width));
    svg.setAttribute('height', String(canvas.height));
    svg.style.position = 'absolute';
    svg.style.top = '0';
    svg.style.left = '0';
    svg.style.pointerEvents = 'none';

    for (const ann of pageAnn) {
      if (ann.type === 'highlight' || ann.type === 'underline') {
        for (const rect of ann.rects) {
          if (rect.page_index !== currentPage - 1) continue;
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          el.setAttribute('x', String(rect.x * scale));
          el.setAttribute('y', String(rect.y * scale));
          el.setAttribute('width', String(rect.width * scale));
          el.setAttribute('height', String(rect.height * scale));
          el.setAttribute('fill', ann.type === 'highlight' ? ann.color + '40' : 'none');
          if (ann.type === 'underline') {
            el.setAttribute('stroke', ann.color);
            el.setAttribute('stroke-width', '2');
          }
          svg.appendChild(el);
        }
      }
    }
  }, [annotations, currentPage, scale, containerRef]);

  return <svg ref={svgRef} />;
}
```

- [ ] **Step 2: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scholarai-workbench/src/components/reader/PdfAnnotations.tsx
git commit -m "feat: add PdfAnnotations SVG overlay for highlight and underline rendering"
```

---

### Task 11: ViewerHost

**Files:**
- Create: `scholarai-workbench/src/components/reader/ViewerHost.tsx`

- [ ] **Step 1: Create ViewerHost**

Create `scholarai-workbench/src/components/reader/ViewerHost.tsx`:
```typescript
import { useState, useEffect } from 'react';
import { FileText, AlertCircle } from 'lucide-react';
import PdfViewer from './PdfViewer';
import MarkdownEditor from './MarkdownEditor';
import AnnotationSidebar from './AnnotationSidebar';
import { resolvePaperFiles, loadDocument } from './DocumentResolver';
import type { PaperFiles, DocumentLoadResult } from './types';

interface ViewerHostProps {
  paperId: string;
  libraryId: string;
}

export default function ViewerHost({ paperId, libraryId }: ViewerHostProps) {
  const [paperFiles, setPaperFiles] = useState<PaperFiles | null>(null);
  const [document, setDocument] = useState<DocumentLoadResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    resolvePaperFiles(paperId, libraryId)
      .then((files) => {
        if (cancelled) return;
        setPaperFiles(files);
        return loadDocument(files);
      })
      .then((doc) => {
        if (cancelled) return;
        setDocument(doc);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e.message);
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [paperId, libraryId]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <FileText className="w-8 h-8 text-outline animate-pulse mx-auto" />
          <p className="text-sm text-on-surface-variant">Loading document...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <AlertCircle className="w-8 h-8 text-error mx-auto" />
          <p className="text-sm text-error">{error}</p>
        </div>
      </div>
    );
  }

  if (!document || document.type === 'none') {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface-container-low">
        <div className="text-center space-y-3">
          <FileText className="w-8 h-8 text-outline mx-auto" />
          <p className="text-sm text-on-surface-variant">No readable file available for this paper.</p>
          <p className="text-xs text-outline">paperId: {paperId}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        {document.type === 'pdf' && document.data instanceof Uint8Array && (
          <PdfViewer data={document.data} fileName={document.fileName} />
        )}
        {document.type === 'markdown' && typeof document.data === 'string' && (
          <MarkdownEditor content={document.data} fileName={document.fileName} />
        )}
        {document.type === 'html' && typeof document.data === 'string' && (
          <div className="flex-1 overflow-auto p-6 bg-surface-container-lowest">
            <div className="max-w-[800px] mx-auto" dangerouslySetInnerHTML={{ __html: document.data }} />
          </div>
        )}
      </div>

      {document.type === 'pdf' && (
        <AnnotationSidebar
          paperId={paperId}
          isOpen={sidebarOpen}
          onToggle={() => setSidebarOpen(!sidebarOpen)}
        />
      )}

      {!sidebarOpen && document.type === 'pdf' && (
        <button
          className="absolute right-4 top-16 px-2 py-1 text-[10px] font-mono bg-surface-container border border-outline-variant rounded hover:bg-surface-container-low z-10"
          onClick={() => setSidebarOpen(true)}
        >
          Annotations
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add scholarai-workbench/src/components/reader/ViewerHost.tsx
git commit -m "feat: add ViewerHost for file type detection and viewer dispatch"
```

---

### Task 12: Rewrite ReaderView Shell

**Files:**
- Modify: `scholarai-workbench/src/components/ReaderView.tsx` (complete rewrite)
- Modify: `scholarai-workbench/src/App.tsx` (minor: ensure paper context available)

- [ ] **Step 1: Rewrite ReaderView**

Replace `scholarai-workbench/src/components/ReaderView.tsx`:
```typescript
import { BookOpen, FileText, ArrowLeft } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { PaperDetail, VariableDetail } from '../types';
import ViewerHost from './reader/ViewerHost';

export default function ReaderView() {
  const {
    selectedPaperId,
    selectedPaperLibraryId,
    setSelectedPaperId,
    selectedNodeId,
    selectedNodeLibraryId,
    setCurrentView,
  } = useApp();

  if (!selectedPaperId && !selectedNodeId) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-4">
          <BookOpen className="w-12 h-12 text-outline mx-auto" />
          <h3 className="text-lg font-medium text-on-surface">Document Reader</h3>
          <p className="text-sm text-on-surface-variant max-w-md">
            Select a paper from the Graph or Library view to read its full text.
            Supports PDF and Markdown documents.
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
          onClick={() => {
            setSelectedPaperId(null);
            setCurrentView('graph');
          }}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="flex items-center gap-2 ml-2">
          <FileText className="w-4 h-4 text-secondary" />
          <span className="text-xs font-mono text-on-surface truncate max-w-[400px]">
            {selectedPaperId || selectedNodeId || 'Document'}
          </span>
        </div>
      </div>

      {selectedPaperId ? (
        <ViewerHost paperId={selectedPaperId} libraryId={selectedPaperLibraryId} />
      ) : selectedNodeId ? (
        <div className="flex-1 flex items-center justify-center bg-surface-container-low">
          <div className="text-center space-y-3">
            <BookOpen className="w-8 h-8 text-outline mx-auto" />
            <p className="text-sm text-on-surface-variant">
              Variable detail view — select a paper to open documents.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 2: Update api.ts with getPaperFiles**

In `scholarai-workbench/src/api.ts`, add to the `graph` object:
```typescript
paperFiles(id: string, libraryId: string = ''): Promise<import('./types').PaperFiles> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
  return jsonFetch(`/paper/${encodeURIComponent(id)}/files${params}`);
},
```

- [ ] **Step 3: Verify props don't need extra App.tsx changes**

Check `App.tsx`: `selectedPaperId` and `selectedPaperLibraryId` already flow through context into `ReaderView`. No changes needed.

- [ ] **Step 4: Type check**

Run: `npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scholarai-workbench/src/components/ReaderView.tsx scholarai-workbench/src/api.ts
git commit -m "feat: rewrite ReaderView as document shell with ViewerHost integration"
```

---

### Task 13: Integration Verification

**Files:**
- No new files — verify the build compiles

- [ ] **Step 1: Full type check**

Run: `npm run lint`
Expected: TypeScript compilation succeeds with no errors

- [ ] **Step 2: Build check**

Run: `npm run build`
Expected: Vite build succeeds

- [ ] **Step 3: Run all tests**

Run: `npm test`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: verify full integration build and tests pass"
```

---

## Verification Checklist

After all tasks complete, verify:
1. `npm run lint` — no TypeScript errors
2. `npm test` — all tests pass
3. `npm run build` — Vite builds successfully
4. Backend `GET /paper/{id}/files` returns valid JSON for papers with files
5. Electron app launches and `desktopShell.readLocalFile` is available in dev console
