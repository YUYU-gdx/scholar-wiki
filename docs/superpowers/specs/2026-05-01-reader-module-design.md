# Reader Module Design

## Overview

Transform `ReaderView` from a structured knowledge-graph paper/variable detail display into a full document reader supporting:
- **PDF reading** with annotation (highlight, underline, notes, ink)
- **Markdown reading/editing** with Live Preview and rendered Reading View

## Architecture

**Pattern: Reader Shell + Pluggable Viewers (Approach B)**

`ReaderView` is a thin shell providing toolbar, navigation, and annotation sidebar. It hosts pluggable viewer components (`PdfViewer`, `MarkdownEditor`) that share a unified interface.

### Component Tree

```
ReaderView (shell)
├── ReaderToolbar          — file info, zoom, search, mode switch
├── ViewerHost             — file type detection → dispatches correct viewer
│   ├── PdfViewer          — pdf.js v4 rendering
│   │   ├── iframe         — pdfjs-dist viewer
│   │   ├── PdfAnnotations — SVG overlay (highlights, ink paths)
│   │   └── SelectionLayer — DOM text layer for text selection
│   └── MarkdownEditor     — CodeMirror 6 + remark
│       ├── LivePreview    — CM6 decorations (hide md syntax, render widgets)
│       └── ReadMode       — react-markdown static render
├── AnnotationSidebar      — annotation list by page/type + edit panel
│   ├── AnnotationList
│   └── AnnotationEditor
├── DocumentResolver       — paper_id → local file path mapping
└── AnnotationManager      — IndexedDB CRUD for annotations
```

### Data Flow

```
paper_id + library_id (AppContext)
  → /paper/{id} API → paper detail (source_pdf_path, mineru_output_path, html_path)
  → DocumentResolver → determine file type and local path
  → Electron main process reads file from disk
  → Renderer receives Uint8Array (PDF) or string (MD)
  → ViewerHost dispatches PdfViewer or MarkdownEditor
  → User annotations → AnnotationManager → IndexedDB
  → (future) annotations linked to knowledge graph nodes
```

## Viewer Components

### PdfViewer

- **Engine**: pdf.js v4 (`pdfjs-dist`), embedded via iframe loading `viewer.html`
- **Text selection**: pdf.js `TextLayer` (DOM-based, not Canvas). Uses `TextLayerBuilder` + `EventBus` for mouse-driven selection with character-level precision.
- **Annotation rendering**: Dedicated `AnnotationLayer` using:
  - SVG overlay: colored semi-transparent rectangles for highlights, paths for underlines
  - Canvas overlay: freehand ink paths, image region annotations
  - Note icons at point positions
- **File loading**: Electron main process reads PDF binary → `Uint8Array` → pdf.js `getDocument()`
- **Communication**: iframe ↔ parent via `postMessage` for selection coordinates and annotation CRUD commands

### MarkdownEditor

- **Engine**: CodeMirror 6 (`@codemirror/view` + `@codemirror/lang-markdown`)
- **Live Preview**: CM6 decoration system:
  - `Decoration.replace`: hide raw Markdown syntax (`**`, `##`, `[link]()`)
  - `Decoration.widget`: render rich embeds (code blocks, tables, mermaid diagrams)
  - Cursor-in-region detection: decorations removed when editing
- **Reading View**: `react-markdown` + `remark-gfm` + `remark-math` + KaTeX
  - Custom components for: `[[wikiLinks]]`, `![[embeds]]`, `==highlights==`, knowledge graph node references
- **Syntax extensions**: remark plugins for Obsidian-like syntax
- **Modes**: `edit | live-preview | read`, controlled via props

## Document Resolution

### paper_id → File Path Mapping

1. Frontend calls `GET /paper/{id}` (existing API)
2. Response includes `source_pdf_path`, `mineru_output_path`, `offline_html_path`
3. `DocumentResolver` determines available files:
   - `.pdf` → trigger `PdfViewer`
   - `.md` (from `mineru_output_path`) → trigger `MarkdownEditor`
   - `.html` → fallback display
4. Electron main process (`preload.cjs`) exposes `readLocalFile(path)` API returning `Uint8Array | string`
5. File is loaded and passed to appropriate viewer

### File Storage Layout (reference)

```
{KN_GRAPH_DATA_DIR}/  (default: D:\KNGraphApp)
└── libraries/
    └── workspaces/
        └── {library_id}/
            └── corpus/
                └── papers/
                    └── {paper_key}/         (doi_xxx or hash_xxx)
                        ├── source/{name}.pdf
                        ├── derived/mineru/latest/    (MinerU markdown output)
                        ├── derived/html/{title}.html
                        └── meta/paper.json           (all file paths)
```

## Annotation Data Model

```typescript
interface Annotation {
  id: string;                    // uuid
  paper_id: string;              // source paper
  library_id: string;            // source library
  type: "highlight" | "underline" | "note" | "ink";
  page_index: number;            // 0-based page number (PDF only)
  rects: AnnotationRect[];       // bounding rectangles in page coords
  text: string;                  // selected text for text annotations
  comment: string;               // user note text
  color: string;                 // hex color
  ink_paths: InkPath[];          // for ink annotations: stroke paths
  linked_node_ids: string[];     // linked knowledge graph variable nodes
  created_at: string;            // ISO timestamp
  updated_at: string;
}

interface AnnotationRect {
  x: number; y: number;
  width: number; height: number;
  page_index: number;
}

interface InkPath {
  points: { x: number; y: number }[];
  width: number;
  color: string;
}
```

### Storage

Annotations are stored client-side in **IndexedDB** (no backend storage needed initially). The `AnnotationManager` provides CRUD operations with:
- Query by paper_id
- Query by page range
- Batch operations (delete all for paper, export/import)

Future: export annotations to knowledge graph via `linked_node_ids` relationships.

## Backend Changes

### New API: `GET /paper/{id}/files`

Returns available readable file paths for a paper:

```json
{
  "paper_id": "doi_smith2023",
  "library_id": "supply_chain",
  "files": {
    "pdf": { "path": "D:\\KNGraphApp\\...", "name": "smith2023.pdf", "size_bytes": 2345678 },
    "markdown": { "path": "D:\\KNGraphApp\\...", "name": "smith2023.md", "size_bytes": 45678 },
    "html": { "path": "D:\\KNGraphApp\\...", "name": "smith2023.html", "size_bytes": 123456 }
  },
  "default_view": "pdf"  // preferred viewer based on available files
}
```

### Electron Preload Extension

New preload API exposed to renderer:

```typescript
interface ElectronAPI {
  readLocalFile(path: string): Promise<Uint8Array>;
  readLocalText(path: string): Promise<string>;
  getFileStats(path: string): Promise<{ size: number; mtime: string }>;
}
```

## File Structure

```
scholarai-workbench/
├── src/
│   ├── components/
│   │   ├── ReaderView.tsx          — Reader Shell (modified)
│   │   └── reader/
│   │       ├── ViewerHost.tsx       — file type detection + viewer dispatch
│   │       ├── PdfViewer.tsx        — pdf.js iframe wrapper
│   │       ├── PdfAnnotations.tsx   — annotation SVG/Canvas overlay
│   │       ├── MarkdownEditor.tsx   — CM6 + react-markdown integration
│   │       ├── AnnotationSidebar.tsx— annotation list/edit panel
│   │       ├── AnnotationManager.ts — IndexedDB CRUD
│   │       ├── DocumentResolver.ts  — paper_id → file path resolution
│   │       └── types.ts            — reader-specific type definitions
│   ├── api.ts                       — + getPaperFiles, + saveAnnotations (future)
│   └── types.ts                     — extended PaperDetail
├── electron/
│   └── preload.cjs                  — local file read APIs
├── package.json                     — + pdfjs-dist, @codemirror/*, remark, react-markdown
└── vite.config.ts                   — (no changes needed)
```

## Dependencies to Add

```json
{
  "pdfjs-dist": "^4.x",
  "@codemirror/view": "^6.x",
  "@codemirror/state": "^6.x",
  "@codemirror/lang-markdown": "^6.x",
  "react-markdown": "^9.x",
  "remark-gfm": "^4.x",
  "remark-math": "^6.x",
  "rehype-katex": "^7.x",
  "katex": "^0.16.x",
  "idb": "^8.x"
}
```

## Implementation Order

1. **DocumentResolver** + Backend API `/paper/{id}/files`
2. **PdfViewer** basic rendering (pdf.js v4 integration, electron file loading)
3. **MarkdownEditor** basic rendering (CM6 + react-markdown)
4. **ViewerHost** + mode switching
5. **PdfAnnotations** + text selection layer
6. **AnnotationSidebar** + AnnotationManager (IndexedDB)
7. **ReaderToolbar** (zoom, search, navigation)
8. Wire into **ReaderView** shell

## Non-Goals (This Phase)

- EPUB/HTML document support
- Real-time collaboration on annotations
- Annotation sync across devices
- Full PDF form filling or digital signatures
- Graph-based annotation analysis
- Mobile support
