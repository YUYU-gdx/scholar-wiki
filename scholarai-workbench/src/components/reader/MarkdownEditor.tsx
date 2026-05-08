import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
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
import Outline from './Outline';
import { readerNotesManager } from './ReaderNotesManager';
import { addNoteToMarkdownAtomic, addNoteToMarkdownAtomicByLine, deleteNoteFromMarkdownAny, extractNoteBlocks, listRecordedNotesMarkdownPaths, readMarkdownText, setRecordedNotesMarkdownPath } from './NoteMarkdownSync';

// CodeMirror 6 imports
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightSpecialChars, drawSelection, rectangularSelection, crosshairCursor, highlightActiveLine } from '@codemirror/view';
import { EditorState } from '@codemirror/state';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { languages } from '@codemirror/language-data';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { syntaxHighlighting, defaultHighlightStyle, bracketMatching, foldGutter, indentOnInput } from '@codemirror/language';
import { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { wikiLinkCompletionSource, wikiLinkPlugin, setWikiLinkNodeCache } from './WikiLink';
import { useApp } from '../../App';

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

function toFileUrl(absPath: string): string {
  const win = String(absPath || '').replace(/\\/g, '/');
  const withLeading = /^[a-zA-Z]:\//.test(win) ? `/${win}` : win;
  return `file://${encodeURI(withLeading)}`;
}

function resolveLocalResourceUrl(raw: string, markdownAbsolutePath: string): string {
  const s = String(raw || '').trim();
  if (!s) return s;
  if (s.startsWith('http://') || s.startsWith('https://') || s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('#')) {
    return s;
  }
  const mdPath = String(markdownAbsolutePath || '');
  if (!mdPath) return s;
  const mdDir = mdPath.replace(/[\\/][^\\/]*$/, '');
  let rel = s;
  if (s.startsWith('/paper/') && s.includes('/asset?')) {
    try {
      const u = new URL(s, 'http://localhost');
      const qp = u.searchParams.get('rel_path');
      if (qp) rel = qp;
    } catch {
      // keep original rel
    }
  }
  if (/^[a-zA-Z]:[\\/]/.test(rel) || rel.startsWith('/')) {
    return toFileUrl(rel);
  }
  const baseDir = mdDir.endsWith('/') || mdDir.endsWith('\\') ? mdDir : `${mdDir}/`;
  const primary = new URL(rel, toFileUrl(baseDir)).toString();
  const marker = '\\final_named\\';
  const markerPos = mdPath.toLowerCase().indexOf(marker.toLowerCase());
  if (markerPos < 0) return primary;
  const fileStem = (mdPath.split(/[/\\]/).pop() || '').replace(/\.[^.]+$/, '');
  if (!fileStem) return primary;
  const root = mdPath.slice(0, markerPos);
  const unpackedBase = `${root}\\unpacked\\${fileStem}\\`;
  return new URL(rel, toFileUrl(unpackedBase)).toString();
}

function fileUrlToPath(fileUrl: string): string {
  try {
    const u = new URL(fileUrl);
    if (u.protocol !== 'file:') return '';
    const decoded = decodeURIComponent(u.pathname || '');
    if (/^\/[a-zA-Z]:\//.test(decoded)) return decoded.slice(1).replace(/\//g, '\\');
    return decoded;
  } catch {
    return '';
  }
}

function guessMimeByPath(p: string): string {
  const lower = String(p || '').toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.gif')) return 'image/gif';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.svg')) return 'image/svg+xml';
  if (lower.endsWith('.bmp')) return 'image/bmp';
  return 'application/octet-stream';
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
  const [text, setText] = useState(content);
  const [renderedHtml, setRenderedHtml] = useState('');
  const [selectionUI, setSelectionUI] = useState({ visible: false, x: 0, y: 0, text: '', lineEnd: -1 });
  const [translationOpen, setTranslationOpen] = useState(false);
  const [translationText, setTranslationText] = useState('');
  const [noteRanges, setNoteRanges] = useState<Array<{ start: number; end: number; id: string; quote: string; note: string }>>([]);

  // CM6 refs
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);
  const currentContentRef = useRef(content);

  // Ref for onContentChange to avoid stale closures in CM6 updateListener
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);

  useEffect(() => {
    setText(content);
    currentContentRef.current = content;
  }, [content]);

  // Auto-save: 150ms debounced write to disk
  useEffect(() => {
    if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
    if (mode === 'read') return;
    const timer = window.setTimeout(async () => {
      await window.desktopShell?.writeLocalText(absolutePath, text);
    }, 150);
    return () => window.clearTimeout(timer);
  }, [text, absolutePath, mode]);

  // Read mode: use fs.watch for instant external change detection (like VS Code/Obsidian).
  useEffect(() => {
    if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
    if (mode !== 'read') return;

    window.desktopShell.watchFile(absolutePath);

    const unsubscribe = window.desktopShell.onFileChanged((payload: { path: string; event: string }) => {
      if (payload.path !== absolutePath) return;
      window.desktopShell?.readLocalText(absolutePath).then((r) => {
        if (!r?.ok) return;
        const disk = String(r.data || '');
        const current = currentContentRef.current;
        if (disk !== current) {
          currentContentRef.current = disk;
          setText(disk);
          onContentChange?.(disk);
        }
      });
    });

    return () => {
      unsubscribe();
      window.desktopShell?.unwatchFile(absolutePath);
    };
  }, [absolutePath, mode, onContentChange]);

  const handleModeChange = (newMode: ViewerMode) => {
    setMode(newMode);
    onModeChange?.(newMode);
  };

  const md = useMemo(() => (
    new MarkdownIt({
      html: true,
      linkify: true,
      typographer: true,
      breaks: false,
    })
      .use(markdownItFootnote)
      .use(markdownItTaskLists, { enabled: true, label: true })
      .use(markdownItMark)
      .use(markdownItDeflist)
      .use(markdownItKatex)
  ), []);

  useEffect(() => {
    const openRules = ['paragraph_open', 'heading_open', 'blockquote_open', 'list_item_open'];
    for (const ruleName of openRules) {
      const base = md.renderer.rules[ruleName];
      md.renderer.rules[ruleName] = (tokens, idx, options, env, self) => {
        const t = tokens[idx];
        const map = t.map || null;
        if (map && map.length >= 2) {
          t.attrSet('data-src-line-start', String(map[0]));
          t.attrSet('data-src-line-end', String(Math.max(map[0], map[1] - 1)));
        }
        return base ? base(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options);
      };
    }
  }, [md]);

  const findReaderNoteRanges = (raw: string): Array<{ start: number; end: number; id: string; quote: string; note: string }> =>
    extractNoteBlocks(raw).map((x) => {
      const quoteMatch = x.text.match(/>\s*(?:Quote|寮曠敤)锛?\s*\n>\s*([\s\S]*?)\n>\s*\n>\s*(?:Note|绗旇)锛?/);
      const noteMatch = x.text.match(/>\s*(?:Note|绗旇)锛?\s*\n>\s*([\s\S]*?)\n>\s*\n>\s*(?:Time|鏃堕棿)锛?/);
      return {
        start: x.start,
        end: x.end,
        id: x.id,
        quote: String(quoteMatch?.[1] || '').trim(),
        note: String(noteMatch?.[1] || '').trim(),
      };
    });

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const clean = DOMPurify.sanitize(md.render(text), {
        ALLOWED_TAGS: [
          'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'strong', 'em', 's', 'mark', 'u', 'sub', 'sup',
          'blockquote', 'code', 'pre', 'span', 'div',
          'ul', 'ol', 'li', 'input', 'label',
          'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
          'a', 'img', 'details', 'summary', 'dl', 'dt', 'dd',
        ],
        ALLOWED_ATTR: [
          'href', 'src', 'alt', 'title', 'target', 'rel',
          'class', 'id', 'type', 'checked', 'disabled',
          'colspan', 'rowspan', 'align', 'style',
          'data-src-line-start', 'data-src-line-end',
        ],
        ALLOWED_URI_REGEXP: /^(?:(?:https?|file|data|blob):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
      });
      const parser = new DOMParser();
      const doc = parser.parseFromString(clean, 'text/html');
      const rewriteAttr = async (el: Element, key: 'src' | 'href') => {
        const raw = el.getAttribute(key);
        if (!raw) return;
        let next = resolveLocalResourceUrl(raw, absolutePath);
        if (window.desktopShell?.runtime === 'electron' && absolutePath && !next.startsWith('http://') && !next.startsWith('https://') && !next.startsWith('data:') && !next.startsWith('blob:') && !next.startsWith('file://')) {
          const r = await window.desktopShell.resolveLocalAsset(absolutePath, raw);
          if (r?.ok && r.path) next = toFileUrl(r.path);
        }
        if (window.desktopShell?.runtime === 'electron' && absolutePath && next.startsWith('file://')) {
          const relTry = raw.startsWith('file://') ? '' : raw;
          if (relTry) {
            const r = await window.desktopShell.resolveLocalAsset(absolutePath, relTry);
            if (r?.ok && r.path) next = toFileUrl(r.path);
          }
        }
        if (key === 'src' && next.startsWith('file://') && window.desktopShell?.runtime === 'electron') {
          const localPath = fileUrlToPath(next);
          if (localPath) {
            const read = await window.desktopShell.readLocalFile(localPath);
            if (read?.ok && read.data) {
              const mime = guessMimeByPath(localPath);
              next = `data:${mime};base64,${read.data}`;
            }
          }
        }
        el.setAttribute(key, next);
      };
      await Promise.all(Array.from(doc.querySelectorAll('img')).map((el) => rewriteAttr(el, 'src')));
      await Promise.all(Array.from(doc.querySelectorAll('a')).map((el) => rewriteAttr(el, 'href')));
      const notes = findReaderNoteRanges(text);
      let noteIdx = 0;
      for (const bq of Array.from(doc.querySelectorAll('blockquote'))) {
        const t = String(bq.textContent || '');
        if (!t.includes('[!NOTE] Reader Note')) continue;
        const idx = noteIdx;
        const noteId = notes[idx]?.id || '';
        noteIdx += 1;
        const wrapper = doc.createElement('div');
        wrapper.setAttribute('data-reader-note-idx', String(idx));
        wrapper.setAttribute('style', 'position:relative;');
        const delBtn = doc.createElement('button');
        delBtn.textContent = '鍒犻櫎绗旇';
        delBtn.setAttribute('type', 'button');
        delBtn.setAttribute('data-reader-note-delete', String(idx));
        if (noteId) delBtn.setAttribute('data-reader-note-id', noteId);
        delBtn.setAttribute('style', 'position:absolute;top:6px;right:6px;font-size:11px;padding:2px 6px;border:1px solid #94a3b8;border-radius:6px;background:#fff;cursor:pointer;');
        const parent = bq.parentNode;
        if (parent) {
          parent.insertBefore(wrapper, bq);
          wrapper.appendChild(bq);
          wrapper.appendChild(delBtn);
        }
      }
      if (!cancelled) setNoteRanges(notes);
      if (!cancelled) setRenderedHtml(doc.body.innerHTML);
    };
    run();
    return () => { cancelled = true; };
  }, [absolutePath, md, text]);

  useEffect(() => {
    if (mode !== 'read' && mode !== 'live-preview') {
      setSelectionUI({ visible: false, x: 0, y: 0, text: '', lineEnd: -1 });
      return;
    }
    const onUp = () => {
      const sel = window.getSelection();
      const raw = sel?.toString() || '';
      const picked = raw.trim();
      if (!picked || !sel || sel.rangeCount === 0) {
        return;
      }
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      const startEl = (range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement)?.closest('[data-src-line-start]') as HTMLElement | null;
      const endEl = (range.endContainer instanceof Element ? range.endContainer : range.endContainer.parentElement)?.closest('[data-src-line-end]') as HTMLElement | null;
      const startLine = Number(startEl?.getAttribute('data-src-line-start') || '-1');
      const anchorBlockEnd = Number(startEl?.getAttribute('data-src-line-end') || '-1');
      const focusLineEnd = Number(endEl?.getAttribute('data-src-line-end') || '-1');
      const coreRaw = raw.replace(/\n\s*$/, '');
      const selectedNewlineCount = (coreRaw.match(/\n/g) || []).length;
      let lineEnd = startLine >= 0 ? (startLine + selectedNewlineCount) : -1;
      if (lineEnd < 0) {
        lineEnd = anchorBlockEnd >= 0 ? anchorBlockEnd : Math.max(startLine, focusLineEnd);
      }
      if (anchorBlockEnd >= 0) {
        lineEnd = Math.min(lineEnd, anchorBlockEnd);
      }
      setSelectionUI({
        visible: true,
        x: Math.max(12, rect.left),
        y: Math.max(12, rect.bottom + 8),
        text: picked,
        lineEnd,
      });
    };
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mouseup', onUp);
    };
  }, [mode]);

  useEffect(() => {
    const onExternalDelete = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string; noteId?: string }>;
      if (String(e.detail?.paperId || '') !== String(paperId || '')) return;
      const noteId = String(e.detail?.noteId || '').trim();
      if (!noteId) return;
      const marker = `> Note ID: ${noteId}`;
      const at = text.indexOf(marker);
      if (at < 0) return;
      const start = text.lastIndexOf('> [!NOTE] Reader Note', at);
      if (start < 0) return;
      let end = text.indexOf('\n\n', at + marker.length);
      if (end < 0) end = text.length;
      const next = `${text.slice(0, start)}${text.slice(end)}`.replace(/\n{3,}/g, '\n\n');
      setText(next);
      onContentChange?.(next);
      if (window.desktopShell?.runtime === 'electron' && absolutePath) {
        window.desktopShell.writeLocalText(absolutePath, next).catch(() => {});
      }
    };
    window.addEventListener('reader-note-md-deleted', onExternalDelete as EventListener);
    return () => window.removeEventListener('reader-note-md-deleted', onExternalDelete as EventListener);
  }, [paperId, text, absolutePath, onContentChange]);

  const handleTranslate = async () => {
    try {
      const cfg = await api.chat.getTranslationProviderConfig();
      const result = await api.chat.translate(selectionUI.text, cfg);
      setTranslationText(result.translated_text || '');
      setTranslationOpen(true);
    } catch (e) {
      setTranslationText(`缈昏瘧澶辫触锛?{(e as Error).message}`);
      setTranslationOpen(true);
    }
  };

  const handleSaveNote = async (note: string) => {
    try {
      const noteText = String(note || '').trim();
      const picked = String(selectionUI.text || '').trim();
      if (!noteText || !picked) return;
      if (absolutePath) setRecordedNotesMarkdownPath(libraryId, paperId, absolutePath);
      // eslint-disable-next-line no-console
      console.log('[notes] markdown save path alignment', {
        absolutePath,
        cachedPaths: listRecordedNotesMarkdownPaths(libraryId, paperId),
        paperId,
        libraryId,
      });
      const saved = await readerNotesManager.add({
        paper_id: paperId,
        library_id: libraryId,
        doc_type: 'markdown',
        page_index: 0,
        selected_text: picked,
        note_text: noteText,
        md_anchor: readerNotesManager.makeAnchor(text, picked),
        markdown_path_at_write: absolutePath,
      });
      const atomic = selectionUI.lineEnd >= 0
        ? await addNoteToMarkdownAtomicByLine(absolutePath, saved.id, picked, noteText, selectionUI.lineEnd)
        : await addNoteToMarkdownAtomic(absolutePath, saved.id, picked, noteText);
      if (!atomic.ok) throw new Error('md_atomic_add_failed');
      // eslint-disable-next-line no-console
      console.log('[notes] markdown save atomic result', { noteId: saved.id, rawLen: atomic.raw.length, hasMarker: atomic.raw.includes(`> Note ID: ${saved.id}`) });
      setText(atomic.raw);
      onContentChange?.(atomic.raw);
      if (window.desktopShell?.runtime === 'electron' && absolutePath) {
        const marker = `> Note ID: ${saved.id}`;
        window.setTimeout(async () => {
          const r = await window.desktopShell?.readLocalText(absolutePath);
          const stillExists = !!(r?.ok && String(r.data || '').includes(marker));
          // eslint-disable-next-line no-console
          console.log('[notes] markdown delayed verify 1s', { noteId: saved.id, stillExists, absolutePath });
          if (!stillExists && r?.ok) {
            const repair = await addNoteToMarkdownAtomic(absolutePath, saved.id, picked, noteText);
            // eslint-disable-next-line no-console
            console.warn('[notes] markdown repaired after overwrite (1s)', { noteId: saved.id, ok: repair.ok });
          }
        }, 1000);
        window.setTimeout(async () => {
          const r = await window.desktopShell?.readLocalText(absolutePath);
          const stillExists = !!(r?.ok && String(r.data || '').includes(marker));
          // eslint-disable-next-line no-console
          console.log('[notes] markdown delayed verify 3s', { noteId: saved.id, stillExists, absolutePath });
        }, 3000);
      }
      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
      setSelectionUI((p) => ({ ...p, visible: false, lineEnd: -1 }));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[notes] markdown save failed', e);
      window.alert(`保存笔记失败：${(e as Error).message}`);
    }
  };

  const handleDeleteNoteByIndex = async (index: number) => {
    if (!Number.isInteger(index) || index < 0 || index >= noteRanges.length) return;
    const range = noteRanges[index];
    if (range.id) {
      readerNotesManager.remove(range.id).catch(() => {});
    }
    const candidates = Array.from(new Set([
      String(absolutePath || '').trim(),
      ...listRecordedNotesMarkdownPaths(libraryId, paperId),
    ].filter(Boolean)));
    const res = await deleteNoteFromMarkdownAny(candidates, range.id || '', range.quote || '', range.note || '');
    if (!res.ok) {
      window.alert('删除已执行，但未在任何 MD 文件中找到对应笔记块。');
      return;
    }
    const latest = await readMarkdownText(res.path || absolutePath);
    if (latest) {
      setText(latest);
      onContentChange?.(latest);
    }
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
  };

  const renderedMarkdownNode = useMemo(() => (
    <div className="reader-markdown">
      <div
        dangerouslySetInnerHTML={{
          __html: renderedHtml,
        }}
      />
    </div>
  ), [renderedHtml]);

  const handleWikiLinkNavigate = useCallback((target: string) => {
    if (target.startsWith('@')) {
      window.dispatchEvent(new CustomEvent('open-reader-tab', { detail: { paperId: target.slice(1) } }));
    } else if (target.includes('/') || target.includes('\\') || target.includes('.')) {
      window.dispatchEvent(new CustomEvent('open-reader-file', { detail: { path: target } }));
    } else {
      window.dispatchEvent(new CustomEvent('navigate-to-node', { detail: { nodeId: target } }));
    }
  }, []);

  const { graphData } = useApp();
  useEffect(() => {
    if (graphData?.nodes) {
      setWikiLinkNodeCache(graphData.nodes.map((n) => ({ id: n.id, label: n.label || n.name || n.id })));
    }
  }, [graphData]);

  // ---- CM6 setup ----

  // CM6 theme matching existing surface-container-lowest styling
  const cm6Theme = useMemo(() => EditorView.theme({
    '&': {
      backgroundColor: 'transparent',
      height: '100%',
    },
    '.cm-scroller': {
      overflow: 'auto',
    },
    '.cm-content': {
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      fontSize: '13px',
      padding: '24px',
      caretColor: 'var(--on-surface)',
    },
    '.cm-gutters': {
      backgroundColor: 'transparent',
      borderRight: '1px solid var(--outline-variant)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'rgba(0,0,0,0.05)',
    },
    '&.cm-focused': {
      outline: 'none',
    },
  }), []);

  // Memoized CodeMirror extensions
  const cmExtensions = useMemo(() => [
    lineNumbers(),
    highlightActiveLineGutter(),
    highlightSpecialChars(),
    history(),
    foldGutter(),
    drawSelection(),
    highlightActiveLine(),
    rectangularSelection(),
    crosshairCursor(),
    bracketMatching(),
    closeBrackets(),
    autocompletion({ override: [wikiLinkCompletionSource] }),
    wikiLinkPlugin(handleWikiLinkNavigate),
    indentOnInput(),
    syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
    markdown({ base: markdownLanguage, codeLanguages: languages }),
    keymap.of([
      ...defaultKeymap,
      ...historyKeymap,
      ...completionKeymap,
      ...closeBracketsKeymap,
      ...searchKeymap,
    ]),
    highlightSelectionMatches(),
    cm6Theme,
    EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        const newText = update.state.doc.toString();
        currentContentRef.current = newText;
        setText(newText);
        onContentChangeRef.current?.(newText);
      }
    }),
  ], [cm6Theme]);

  // Create/destroy CM6 editor based on mode
  useEffect(() => {
    // If not in an editing mode, destroy any existing CM6 instance
    if (mode !== 'edit' && mode !== 'live-preview') {
      if (editorViewRef.current) {
        editorViewRef.current.destroy();
        editorViewRef.current = null;
      }
      return;
    }

    // Container must be in the DOM
    if (!editorContainerRef.current) return;

    // Clean up any previous editor before creating a new one
    if (editorViewRef.current) {
      editorViewRef.current.destroy();
      editorViewRef.current = null;
    }

    // Create CM6 EditorView mounted on the container div
    const state = EditorState.create({
      doc: currentContentRef.current,
      extensions: cmExtensions,
    });
    const view = new EditorView({ state, parent: editorContainerRef.current });
    editorViewRef.current = view;

    return () => {
      view.destroy();
      editorViewRef.current = null;
    };
  }, [mode, cmExtensions]);

  // Sync external text changes into the active CM6 editor (e.g. after note save/delete,
  // or when content prop changes propagate through setText)
  useEffect(() => {
    const view = editorViewRef.current;
    if (!view) return;
    const currentDoc = view.state.doc.toString();
    if (text !== currentDoc) {
      view.dispatch({
        changes: { from: 0, to: currentDoc.length, insert: text },
      });
    }
  }, [text]);

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
          <div
            ref={editorContainerRef}
            className="w-full h-full bg-surface-container-lowest"
          />
        )}

        {mode === 'read' && (
          <div className="flex h-full">
            <Outline
              content={currentContentRef.current}
              onGoToLine={(line) => {
                // Scroll to heading: find the rendered element by data-src-line-start
                const el = document.querySelector(`[data-src-line-start="${line}"]`);
                el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            />
            <div className="flex-1 overflow-y-auto p-6 max-w-[800px] mx-auto">
            <div
              onClick={(evt) => {
                const rawTarget = evt.target;
                const elem = rawTarget instanceof Element ? rawTarget : ((rawTarget as Node | null)?.parentElement || null);
                const btn = elem?.closest('[data-reader-note-delete]') as HTMLElement | null;
                if (!btn) return;
                const idx = Number(btn.getAttribute('data-reader-note-delete') || '-1');
                if (idx >= 0) handleDeleteNoteByIndex(idx);
              }}
            >
              {renderedMarkdownNode}
            </div>
          </div>
          </div>
        )}

        {mode === 'live-preview' && (
          <div className="flex h-full">
            <div
              ref={editorContainerRef}
              className="flex-1 bg-surface-container-lowest border-r border-outline-variant"
            />
            <div className="flex-1 overflow-y-auto p-4">
              <div
                onClick={(evt) => {
                  const rawTarget = evt.target;
                  const elem = rawTarget instanceof Element ? rawTarget : ((rawTarget as Node | null)?.parentElement || null);
                  const btn = elem?.closest('[data-reader-note-delete]') as HTMLElement | null;
                  if (!btn) return;
                  const idx = Number(btn.getAttribute('data-reader-note-delete') || '-1');
                  if (idx >= 0) handleDeleteNoteByIndex(idx);
                }}
              >
                {renderedMarkdownNode}
              </div>
            </div>
          </div>
        )}
      </div>
      <SelectionActionPopover
        visible={selectionUI.visible}
        x={selectionUI.x}
        y={selectionUI.y}
        selectedText={selectionUI.text}
        onTranslate={handleTranslate}
        onSaveNote={handleSaveNote}
        onClose={() => { setSelectionUI((p) => ({ ...p, visible: false, lineEnd: -1 })); }}
      />
      <TranslationModal open={translationOpen} text={translationText} onClose={() => setTranslationOpen(false)} />
    </div>
  );
}
