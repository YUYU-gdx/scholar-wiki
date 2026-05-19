import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import MarkdownIt from 'markdown-it';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTaskLists from 'markdown-it-task-lists';
import markdownItMark from 'markdown-it-mark';
import markdownItDeflist from 'markdown-it-deflist';
import markdownItKatex from '@vscode/markdown-it-katex';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import 'katex/dist/katex.min.css';
import type { ViewerMode } from './types';
import SelectionActionPopover from './SelectionActionPopover';
import { api } from '../../api';
import Outline from './Outline';
import { deleteNoteFromMarkdownAny, extractNoteBlocks, readMarkdownText, upsertNoteInMarkdown } from './NoteMarkdownSync';

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
import { livePreviewPlugin } from './LivePreviewPlugin';
import { convertScriptOnlyKatexToHtml } from './katexScriptAlignment';
import { useApp } from '../../app-context';
import { isSelectionInside } from './selectionScope';
import { resolveMarkdownLinkPath } from './readerLinks';
import { sanitizeMarkdownBeforeRender } from './MarkdownRenderSanitizer';
import { transformCallouts } from './MarkdownCallout';
import { buildReaderPositionKey, readReaderPosition, writeReaderPosition } from './ReaderPositionStore';
import { hasTranslationBlocks, removeTranslationBlocks } from './TranslationMarkdown';

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

function highlightCodeBlocks(doc: Document): void {
  for (const code of Array.from(doc.querySelectorAll('pre > code'))) {
    const className = code.className || '';
    const lm = className.match(/language-(\w+)/);
    const lang = lm ? lm[1] : '';
    if (!lang || !hljs.getLanguage(lang)) continue;
    try {
      const raw = code.textContent || '';
      const result = hljs.highlight(raw, { language: lang, ignoreIllegals: true });
      code.innerHTML = result.value;
      code.className = `${className} hljs`;
    } catch (_) { /* leave unhighlighted */ }
  }
}

function enhanceCodeBlocks(doc: Document): void {
  for (const pre of Array.from(doc.querySelectorAll('pre'))) {
    const code = pre.querySelector(':scope > code');
    const className = code?.className || '';
    const lm = className.match(/language-(\w+)/);
    const lang = lm ? lm[1] : '';
    if (!lang) continue;

    const header = doc.createElement('div');
    header.className = 'code-block-header';

    const label = doc.createElement('span');
    label.className = 'code-lang-label';
    label.textContent = lang;
    header.appendChild(label);

    const copyBtn = doc.createElement('button');
    copyBtn.className = 'code-copy-btn';
    copyBtn.setAttribute('type', 'button');
    copyBtn.setAttribute('data-code-copy', '');
    copyBtn.textContent = 'Copy';
    header.appendChild(copyBtn);

    const parent = pre.parentNode;
    if (parent) {
      parent.insertBefore(header, pre);
    }
  }
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
  const TRANSLATION_JOB_STORAGE_KEY = 'reader_translation_job_v1';
  const [mode, setMode] = useState<ViewerMode>(initialMode);
  const [text, setText] = useState(content);
  const [renderedHtml, setRenderedHtml] = useState('');
  const [selectionUI, setSelectionUI] = useState({ visible: false, x: 0, y: 0, text: '', lineStart: -1, lineEnd: -1 });
  const [translationLoading, setTranslationLoading] = useState(false);
  const [translationText, setTranslationText] = useState('');
  const [docTranslationRunning, setDocTranslationRunning] = useState(false);
  const [docTranslationProgress, setDocTranslationProgress] = useState(0);
  const [docTranslationStatus, setDocTranslationStatus] = useState('');
  const [docHasActiveTask, setDocHasActiveTask] = useState(false);
  const docTranslationPollingRef = useRef(false);
  const hasDocumentTranslations = useMemo(() => hasTranslationBlocks(text), [text]);
  const [noteRanges, setNoteRanges] = useState<Array<{
    start: number;
    end: number;
    id: string;
    quote: string;
    note: string;
    pageIndex: number;
    rect: string;
    quads: string;
  }>>([]);
  const flashTimerRef = useRef<number | null>(null);

  // CM6 refs
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const selectionHostRef = useRef<HTMLDivElement>(null);
  const readScrollRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);
  const currentContentRef = useRef(content);
  const readerPositionKey = useMemo(() => buildReaderPositionKey({
    libraryId,
    paperId,
    absolutePath,
    viewerType: 'markdown',
  }), [absolutePath, libraryId, paperId]);

  // Ref for onContentChange to avoid stale closures in CM6 updateListener
  const onContentChangeRef = useRef(onContentChange);
  useEffect(() => {
    onContentChangeRef.current = onContentChange;
  }, [onContentChange]);

  useEffect(() => {
    setText(content);
    currentContentRef.current = content;
  }, [content]);

  useEffect(() => {
    if (mode !== 'read') return;
    const el = readScrollRef.current;
    if (!el) return;
    const saved = readReaderPosition(readerPositionKey);
    if (!saved) return;
    const apply = () => {
      el.scrollTop = saved.scrollTop || 0;
      el.scrollLeft = saved.scrollLeft || 0;
    };
    const raf = window.requestAnimationFrame(() => {
      apply();
      window.requestAnimationFrame(apply);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [mode, readerPositionKey, renderedHtml]);

  useEffect(() => {
    if (mode !== 'read') return;
    const el = readScrollRef.current;
    if (!el) return;
    let timer: number | null = null;
    const save = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        writeReaderPosition(readerPositionKey, {
          scrollTop: el.scrollTop,
          scrollLeft: el.scrollLeft,
        });
      }, 120);
    };
    el.addEventListener('scroll', save, { passive: true });
    return () => {
      el.removeEventListener('scroll', save);
      if (timer !== null) window.clearTimeout(timer);
      writeReaderPosition(readerPositionKey, {
        scrollTop: el.scrollTop,
        scrollLeft: el.scrollLeft,
      });
    };
  }, [mode, readerPositionKey]);

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

  const findReaderNoteRanges = (raw: string): Array<{
    start: number;
    end: number;
    id: string;
    quote: string;
    note: string;
    pageIndex: number;
    rect: string;
    quads: string;
  }> =>
    extractNoteBlocks(raw).map((x) => {
      const lines = String(x.text || '').replace(/\r\n/g, '\n').split('\n').map((ln) => ln.replace(/^\s*>\s?/, '').trimEnd());
      let mode: '' | 'quote' | 'note' = '';
      const quoteLines: string[] = [];
      const noteLines: string[] = [];
      let pageIndex = -1;
      let rect = '';
      let quads = '';
      for (const rawLine of lines) {
        const line = String(rawLine || '').trim();
        if (!line) continue;
        if (/^Quote:\s*$/i.test(line)) { mode = 'quote'; continue; }
        if (/^Note:\s*$/i.test(line)) { mode = 'note'; continue; }
        if (/^Time:\s*/i.test(line)) { mode = ''; continue; }
        const pageMatch = line.match(/^Page:\s*(\d+)/i);
        if (pageMatch) {
          pageIndex = Number.parseInt(String(pageMatch[1] || '-1'), 10);
          continue;
        }
        const rectMatch = line.match(/^Rect:\s*(.+)$/i);
        if (rectMatch) {
          rect = String(rectMatch[1] || '').trim();
          continue;
        }
        const quadsMatch = line.match(/^Quads:\s*(.+)$/i);
        if (quadsMatch) {
          quads = String(quadsMatch[1] || '').trim();
          continue;
        }
        if (/^(Note ID|Page|Rect|Quads):/i.test(line)) continue;
        if (mode === 'quote') quoteLines.push(line);
        else if (mode === 'note') noteLines.push(line);
      }
      return {
        start: x.start,
        end: x.end,
        id: x.id,
        quote: quoteLines.join('\n').trim(),
        note: noteLines.join('\n').trim(),
        pageIndex,
        rect,
        quads,
      };
    });

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const clean = DOMPurify.sanitize(md.render(sanitizeMarkdownBeforeRender(text)), {
        ALLOWED_TAGS: [
          'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'strong', 'em', 's', 'mark', 'u', 'sub', 'sup',
          'blockquote', 'code', 'pre', 'span', 'div',
          'ul', 'ol', 'li', 'input', 'label',
          'table', 'caption', 'colgroup', 'col', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
          'a', 'img', 'details', 'summary', 'dl', 'dt', 'dd',
        ],
        ALLOWED_ATTR: [
          'href', 'src', 'alt', 'title', 'target', 'rel',
          'class', 'id', 'type', 'checked', 'disabled',
          'colspan', 'rowspan', 'align', 'style',
          'data-src-line-start', 'data-src-line-end', 'data-original-href',
        ],
        ALLOWED_URI_REGEXP: /^(?:(?:https?|file|data|blob):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
      });
      const parser = new DOMParser();
      const doc = parser.parseFromString(clean, 'text/html');
      convertScriptOnlyKatexToHtml(doc);
      transformCallouts(doc);
      highlightCodeBlocks(doc);
      enhanceCodeBlocks(doc);
      const rewriteAttr = async (el: Element, key: 'src' | 'href') => {
        const raw = el.getAttribute(key);
        if (!raw) return;
        if (key === 'href') el.setAttribute('data-original-href', raw);
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
      // Primary: matched callouts that were transformed from [!NOTE] Reader Note
      for (const callout of Array.from(doc.querySelectorAll('.callout-note'))) {
        const titleEl = callout.querySelector('.callout-title');
        const titleText = String(titleEl?.textContent || '').trim();
        if (titleText !== 'Reader Note') continue;
        // Keep metadata in markdown source, but hide meta fields in rendered reader UI.
        for (const p of Array.from(callout.querySelectorAll('p'))) {
          const t = String(p.textContent || '').trim();
          if (/^(Note ID|Page|Rect|Quads):/i.test(t)) p.remove();
        }
        const idx = noteIdx;
        const noteId = notes[idx]?.id || '';
        noteIdx += 1;
        callout.setAttribute('data-reader-note-idx', String(idx));
        callout.setAttribute('style', 'position:relative;');
        const editBtn = doc.createElement('button');
        editBtn.textContent = '编辑笔记';
        editBtn.setAttribute('type', 'button');
        editBtn.setAttribute('data-reader-note-edit', String(idx));
        if (noteId) editBtn.setAttribute('data-reader-note-id', noteId);
        editBtn.setAttribute('style', 'position:absolute;top:6px;right:74px;font-size:11px;padding:2px 6px;border:1px solid #94a3b8;border-radius:6px;background:#fff;cursor:pointer;');
        callout.appendChild(editBtn);
        const delBtn = doc.createElement('button');
        delBtn.textContent = '删除笔记';
        delBtn.setAttribute('type', 'button');
        delBtn.setAttribute('data-reader-note-delete', String(idx));
        if (noteId) delBtn.setAttribute('data-reader-note-id', noteId);
        delBtn.setAttribute('style', 'position:absolute;top:6px;right:6px;font-size:11px;padding:2px 6px;border:1px solid #94a3b8;border-radius:6px;background:#fff;cursor:pointer;');
        callout.appendChild(delBtn);
      }
      // Fallback: blockquotes that were not transformed (e.g. malformed callout syntax)
      for (const bq of Array.from(doc.querySelectorAll('blockquote'))) {
        const t = String(bq.textContent || '');
        if (!t.includes('[!NOTE] Reader Note')) continue;
        // Old/malformed reader notes fallback: still render with note callout visual style.
        bq.classList.add('callout', 'callout-note');
        const idx = noteIdx;
        const noteId = notes[idx]?.id || '';
        noteIdx += 1;
        const wrapper = doc.createElement('div');
        wrapper.setAttribute('data-reader-note-idx', String(idx));
        wrapper.setAttribute('style', 'position:relative;');
        for (const p of Array.from(bq.querySelectorAll('p'))) {
          const pt = String(p.textContent || '').trim();
          if (/^(Note ID|Page|Rect|Quads):/i.test(pt)) p.remove();
        }
        const editBtn = doc.createElement('button');
        editBtn.textContent = '编辑笔记';
        editBtn.setAttribute('type', 'button');
        editBtn.setAttribute('data-reader-note-edit', String(idx));
        if (noteId) editBtn.setAttribute('data-reader-note-id', noteId);
        editBtn.setAttribute('style', 'position:absolute;top:6px;right:74px;font-size:11px;padding:2px 6px;border:1px solid #94a3b8;border-radius:6px;background:#fff;cursor:pointer;');
        wrapper.appendChild(editBtn);
        const delBtn = doc.createElement('button');
        delBtn.textContent = '删除笔记';
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
      setSelectionUI({ visible: false, x: 0, y: 0, text: '', lineStart: -1, lineEnd: -1 });
      return;
    }
    const host = selectionHostRef.current;
    if (!host) return;
    const onUp = (e: MouseEvent) => {
      // Ignore clicks inside the popover itself (prevents closing when clicking input)
      const target = e.target as Element | null;
      if (target?.closest('.selection-action-popover')) return;

      const sel = window.getSelection();
      if (!isSelectionInside(host, sel)) {
        setSelectionUI((prev) => (prev.visible ? { ...prev, visible: false, lineStart: -1, lineEnd: -1 } : prev));
        return;
      }
      const raw = sel?.toString() || '';
      const picked = raw.trim();
      if (!picked || !sel || sel.rangeCount === 0) {
        setSelectionUI((prev) => (prev.visible ? { ...prev, visible: false, lineStart: -1, lineEnd: -1 } : prev));
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
        lineEnd = anchorBlockEnd >= 0 ? anchorBlockEnd : focusLineEnd;
      }
      // Only trust focusLineEnd if it's within or adjacent to the anchor block
      // (prevents triple-click from overflowing into the next block)
      if (focusLineEnd >= 0) {
        if (anchorBlockEnd >= 0 && focusLineEnd > anchorBlockEnd + 2) {
          // focusLineEnd is in a distant block - ignore, use anchorBlockEnd as cap
          lineEnd = Math.max(lineEnd, anchorBlockEnd);
        } else {
          lineEnd = Math.max(lineEnd, focusLineEnd);
        }
      }
      setSelectionUI({
        visible: true,
        x: Math.max(12, rect.left),
        y: Math.max(12, rect.top - 220),
        text: picked,
        lineStart: startLine,
        lineEnd,
      });
      setTranslationText('');
    };
    host.addEventListener('mouseup', onUp);
    return () => {
      host.removeEventListener('mouseup', onUp);
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

  useEffect(() => {
    const onJump = (evt: Event) => {
      const e = evt as CustomEvent<{ paperId?: string; query?: string }>;
      if (String(e.detail?.paperId || '').trim() !== String(paperId || '').trim()) return;
      const q = String(e.detail?.query || '').replace(/\s+/g, ' ').trim();
      if (!q) return;
      const candidates = (() => {
        const out: string[] = [];
        out.push(q);
        const sentence = q.split(/[.;:!?。；：！？]/)[0]?.trim();
        if (sentence && sentence.length >= 12) out.push(sentence);
        const words = q.split(/\s+/).filter(Boolean);
        if (words.length >= 8) out.push(words.slice(0, 8).join(' '));
        if (words.length >= 5) out.push(words.slice(0, 5).join(' '));
        return Array.from(new Set(out.map((x) => x.toLowerCase())));
      })();

      const tryRendered = () => {
        const host = selectionHostRef.current;
        if (!host) return false;
        const contentRoot = host.querySelector('.reader-markdown') as HTMLElement | null;
        if (!contentRoot) return false;
        const nodes = Array.from(contentRoot.querySelectorAll('p,li,blockquote,td,th,h1,h2,h3,h4,h5,h6')) as HTMLElement[];
        const hit = nodes.find((n) => {
          const textNorm = String(n.textContent || '').replace(/\s+/g, ' ').toLowerCase();
          return candidates.some((c) => textNorm.includes(c));
        });
        if (!hit) return false;
        hit.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const prev = hit.style.backgroundColor;
        const prevTransition = hit.style.transition;
        hit.style.transition = 'background-color 180ms ease';
        hit.style.backgroundColor = 'rgba(251, 191, 36, 0.28)';
        if (flashTimerRef.current) window.clearTimeout(flashTimerRef.current);
        flashTimerRef.current = window.setTimeout(() => {
          hit.style.backgroundColor = prev;
          hit.style.transition = prevTransition;
        }, 1400);
        return true;
      };

      if (mode === 'read') {
        tryRendered();
        return;
      }

      const view = editorViewRef.current;
      if (!view) {
        tryRendered();
        return;
      }
      const doc = view.state.doc.toString();
      const docLower = doc.toLowerCase();
      const idx = candidates.map((c) => docLower.indexOf(c)).find((i) => i >= 0) ?? -1;
      if (idx < 0) {
        tryRendered();
        return;
      }
      view.dispatch({
        selection: { anchor: idx, head: idx + q.length },
        scrollIntoView: true,
      });
    };
    window.addEventListener('reader-search-and-jump', onJump as EventListener);
    return () => window.removeEventListener('reader-search-and-jump', onJump as EventListener);
  }, [paperId, mode]);

  const handleTranslate = async () => {
    try {
      setTranslationLoading(true);
      const cfg = await api.chat.getTranslationProviderConfig();
      const selected = String(selectionUI.text || '').trim();
      const result = await api.chat.translate(selected, cfg, false);
      setTranslationText(result.formatted_text || result.translated_text || '');
    } catch (e) {
      setTranslationText(`Translation failed: ${(e as Error).message}`);
    } finally {
      setTranslationLoading(false);
    }
  };

  const persistTranslationJob = (payload: { job_id: string; absolute_path: string; started_at: number }) => {
    try {
      window.sessionStorage.setItem(TRANSLATION_JOB_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // no-op
    }
  };

  const clearPersistedTranslationJob = () => {
    try {
      window.sessionStorage.removeItem(TRANSLATION_JOB_STORAGE_KEY);
    } catch {
      // no-op
    }
  };

  const loadPersistedTranslationJob = (): { job_id: string; absolute_path: string; started_at: number } | null => {
    try {
      const raw = window.sessionStorage.getItem(TRANSLATION_JOB_STORAGE_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw) as { job_id?: string; absolute_path?: string; started_at?: number };
      const jobId = String(obj?.job_id || '').trim();
      const path = String(obj?.absolute_path || '').trim();
      const startedAt = Number(obj?.started_at || 0);
      if (!jobId || !path || !Number.isFinite(startedAt) || startedAt <= 0) return null;
      return { job_id: jobId, absolute_path: path, started_at: startedAt };
    } catch {
      return null;
    }
  };

  const pollTranslationJobUntilDone = useCallback(async (jobId: string, startedAtMs: number) => {
    if (docTranslationPollingRef.current) return;
    docTranslationPollingRef.current = true;
    setDocTranslationRunning(true);
    setDocHasActiveTask(true);
    try {
      while (docTranslationPollingRef.current) {
        // eslint-disable-next-line no-await-in-loop
        const row = await api.chat.getTranslateJob(jobId);
        setDocTranslationProgress(Math.max(0, Math.min(100, Number(row.progress || 0))));
        setDocTranslationStatus(
          row.status === 'running' || row.status === 'queued'
            ? `进行中 ${Math.max(0, Math.min(100, Number(row.progress || 0)))}%`
            : row.status === 'completed'
              ? '已完成'
              : row.status === 'failed'
                ? '失败'
                : String(row.status || ''),
        );
        if (row.status === 'completed') {
          const translated = String(row.result?.formatted_text || row.result?.translated_text || '').trim();
          if (!translated) throw new Error('translation_result_empty');
          setText(translated);
          currentContentRef.current = translated;
          onContentChange?.(translated);
          if (window.desktopShell?.runtime === 'electron' && absolutePath) {
            await window.desktopShell.writeLocalText(absolutePath, translated);
          }
          clearPersistedTranslationJob();
          setTranslationText('全文对照翻译已完成并写回。');
          setDocTranslationProgress(100);
          setDocHasActiveTask(false);
          return;
        }
        if (row.status === 'failed') {
          clearPersistedTranslationJob();
          setDocHasActiveTask(false);
          throw new Error(String(row.error || 'translation_job_failed'));
        }
        if (Date.now() - startedAtMs > 30 * 60 * 1000) {
          clearPersistedTranslationJob();
          setDocHasActiveTask(false);
          throw new Error('translation_job_timeout');
        }
        // eslint-disable-next-line no-await-in-loop
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
    } finally {
      docTranslationPollingRef.current = false;
      setDocTranslationRunning(false);
    }
  }, [absolutePath, onContentChange]);

  const handleTranslateWholeDocument = async () => {
    try {
      setDocTranslationRunning(true);
      setDocTranslationProgress(0);
      setDocTranslationStatus('提交中 0%');
      const cfg = await api.chat.getTranslationProviderConfig();
      const jobsUnsupportedKey = 'reader_translate_jobs_unsupported';
      const jobsUnsupported = window.sessionStorage.getItem(jobsUnsupportedKey) === '1';
      try {
        if (jobsUnsupported) throw new Error('http_405');
        const submit = await api.chat.submitTranslateJob(currentContentRef.current, cfg, `library:${libraryId || 'default'}`, true);
        const jobId = String(submit.job_id || '').trim();
        if (!jobId) throw new Error('translation_job_id_missing');
        const startedAt = Date.now();
        persistTranslationJob({ job_id: jobId, absolute_path: String(absolutePath || ''), started_at: startedAt });
        await pollTranslationJobUntilDone(jobId, startedAt);
        return;
      } catch (jobErr) {
        // Fallback path: older backend without /chat/translate/jobs.
        const emsg = String((jobErr as Error).message || '');
        if (emsg.includes('http_405')) {
          window.sessionStorage.setItem(jobsUnsupportedKey, '1');
        }
        setDocTranslationStatus('任务接口不可用，回退到同步翻译...');
        setDocTranslationProgress(20);
        setDocHasActiveTask(true);
        const syncResult = await api.chat.translate(currentContentRef.current, cfg, true);
        setDocTranslationProgress(85);
        const translated = String(syncResult.formatted_text || syncResult.translated_text || '').trim();
        if (!translated) throw jobErr;
        setText(translated);
        currentContentRef.current = translated;
        onContentChange?.(translated);
        if (window.desktopShell?.runtime === 'electron' && absolutePath) {
          await window.desktopShell.writeLocalText(absolutePath, translated);
        }
        clearPersistedTranslationJob();
        setDocTranslationProgress(100);
        setDocTranslationStatus('已完成（同步模式）');
        setDocHasActiveTask(false);
        setTranslationText('全文对照翻译已完成并写回。');
        return;
      }
    } catch (e) {
      const msg = String((e as Error).message || 'unknown_error');
      setDocTranslationStatus(`失败: ${msg}`);
      setDocHasActiveTask(false);
      setTranslationText(`全文翻译失败: ${msg}`);
      window.alert(`全文翻译失败：${msg}`);
    } finally {
      setDocTranslationRunning(false);
    }
  };

  const handleRemoveWholeDocumentTranslation = async () => {
    const ok = window.confirm('确定取消翻译吗？\n这会删除当前 Markdown 文件中的所有译文文本块，原文和笔记会保留。');
    if (!ok) return;
    const next = removeTranslationBlocks(currentContentRef.current);
    setText(next);
    currentContentRef.current = next;
    onContentChange?.(next);
    if (window.desktopShell?.runtime === 'electron' && absolutePath) {
      await window.desktopShell.writeLocalText(absolutePath, next);
    }
    setDocTranslationStatus('已删除所有译文块');
    setTranslationText('已取消翻译。');
  };

  useEffect(() => {
    const pending = loadPersistedTranslationJob();
    if (!pending) return;
    if (String(pending.absolute_path || '').trim() !== String(absolutePath || '').trim()) return;
    setDocHasActiveTask(true);
    pollTranslationJobUntilDone(pending.job_id, pending.started_at).catch((e) => {
      const msg = String((e as Error).message || 'unknown_error');
      setDocTranslationStatus(`失败: ${msg}`);
      setTranslationText(`全文翻译失败: ${msg}`);
      setDocHasActiveTask(false);
    });
    return () => {
      docTranslationPollingRef.current = false;
    };
  }, [absolutePath, pollTranslationJobUntilDone]);

  const handleSaveNote = async (note: string) => {
    const noteId = crypto.randomUUID();
    const noteText = String(note || '').trim();
    const picked = String(selectionUI.text || '').trim();
    if (!noteText || !picked) return;

    const sh = window.desktopShell;
    // eslint-disable-next-line no-console
    console.log('[notes] save start', { noteId, absolutePath, hasShell: !!sh, runtime: sh?.runtime, pickedLen: picked.length, noteLen: noteText.length });

    // 鈹€鈹€ Direct file write 鈹€鈹€
    if (!sh || sh.runtime !== 'electron' || !absolutePath) {
      window.alert('文件写入不可用（非 Electron 环境）');
      setTimeout(() => {
        setSelectionUI((p) => ({ ...p, visible: false, lineStart: -1, lineEnd: -1 }));
      }, 600);
      return;
    }

    try {
      const ok = await upsertNoteInMarkdown(absolutePath, noteId, picked, noteText, { anchorText: picked });
      if (!ok) {
        throw new Error('写入验证失败：回读文件未找到笔记标记');
      }
      const latest = await readMarkdownText(absolutePath);
      if (latest) {
        setText(latest);
        onContentChange?.(latest);
      }
      window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId } }));
      // eslint-disable-next-line no-console
      console.log('[notes] save complete', { noteId });
      // Brief success feedback before closing popover
      setTranslationText('已保存');
      setTimeout(() => {
        setSelectionUI((p) => ({ ...p, visible: false, lineStart: -1, lineEnd: -1 }));
      }, 600);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('[notes] file write failed', e);
      window.alert(`写入MD文件失败：${(e as Error).message}`);
    }
  };

  const handleDeleteNoteByIndex = async (index: number) => {
    if (!Number.isInteger(index) || index < 0 || index >= noteRanges.length) return;
    const range = noteRanges[index];
    const candidates = [String(absolutePath || '').trim()].filter(Boolean);
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
    window.dispatchEvent(new CustomEvent('reader-annotation-changed', { detail: { paperId, noteId: range.id || '', action: 'delete' } }));
  };

  const handleEditNoteByIndex = async (index: number) => {
    if (!Number.isInteger(index) || index < 0 || index >= noteRanges.length) return;
    const range = noteRanges[index];
    if (!range?.id) return;
    const nextQuote = window.prompt('编辑 Quote：', range.quote || '');
    if (nextQuote === null) return;
    const nextNote = window.prompt('编辑 Note：', range.note || '');
    if (nextNote === null) return;
    const quote = String(nextQuote || '').trim();
    const note = String(nextNote || '').trim();
    if (!quote || !note) {
      window.alert('Quote 和 Note 不能为空。');
      return;
    }
    const hasPdfLocator = range.pageIndex >= 0 || !!String(range.rect || '').trim() || !!String(range.quads || '').trim();
    const ok = await upsertNoteInMarkdown(
      String(absolutePath || '').trim(),
      range.id,
      quote,
      note,
      hasPdfLocator
        ? { pageIndex: range.pageIndex, rect: range.rect, quads: range.quads, anchorText: quote }
        : { anchorText: quote },
    );
    if (!ok) {
      window.alert('编辑笔记失败：写入 Markdown 失败。');
      return;
    }
    const latest = await readMarkdownText(String(absolutePath || '').trim());
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

  const app = useApp();
  const graphData = app?.graphData ?? null;
  useEffect(() => {
    if (graphData?.nodes) {
      setWikiLinkNodeCache(graphData.nodes.map((n) => ({ id: n.id, label: n.label || n.name || n.id })));
    }
  }, [graphData]);

  // ---- CM6 setup ----

  // CM6 theme for source editing
  const cm6EditTheme = useMemo(() => EditorView.theme({
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

  // CM6 theme for live preview - matches Read mode typography
  const cm6LivePreviewTheme = useMemo(() => EditorView.theme({
    '&': {
      backgroundColor: 'transparent',
      height: '100%',
    },
    '.cm-scroller': {
      overflow: 'auto',
    },
    '.cm-content': {
      fontFamily: '"Newsreader", ui-serif, Georgia, serif',
      fontSize: '16px',
      lineHeight: '1.78',
      padding: '24px 48px',
      maxWidth: '720px',
      margin: '0 auto',
      caretColor: 'var(--on-surface)',
      color: 'var(--color-on-surface)',
      overflowWrap: 'break-word',
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
  const cmExtensions = useMemo(() => {
    const exts = [
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
      mode === 'live-preview' ? cm6LivePreviewTheme : cm6EditTheme,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const newText = update.state.doc.toString();
          currentContentRef.current = newText;
          setText(newText);
          onContentChangeRef.current?.(newText);
        }
      }),
    ];
    if (mode === 'live-preview') {
      exts.push(livePreviewPlugin);
      exts.push(EditorView.lineWrapping);
    }
    return exts;
  }, [cm6EditTheme, cm6LivePreviewTheme, mode]);

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
    <div ref={selectionHostRef} className="flex flex-col h-full bg-surface-container-low">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <span className="text-xs font-mono text-on-surface-variant truncate max-w-[300px]">{fileName}</span>
        <div className="flex items-center gap-1 bg-surface-container rounded-lg p-0.5">
          {(['edit', 'read'] as ViewerMode[]).map((m) => (
            <button
              key={m}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                mode === m
                  ? 'bg-primary-container text-on-primary-container font-medium'
                  : 'text-on-surface-variant hover:bg-surface-container-low'
              }`}
              onClick={() => handleModeChange(m)}
            >
              {m === 'edit' ? 'Edit' : m === 'live-preview' ? 'Live' : 'Read'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-2">
          {!docHasActiveTask && (
            <button
              className="px-3 py-1 text-xs rounded-md border border-outline-variant text-on-surface-variant hover:bg-surface-container-low"
              onClick={hasDocumentTranslations ? handleRemoveWholeDocumentTranslation : handleTranslateWholeDocument}
              disabled={docTranslationRunning}
              title={hasDocumentTranslations ? '删除当前 Markdown 中所有译文块' : '全文段落对照翻译'}
            >
              {hasDocumentTranslations ? '取消翻译' : '全文对照翻译'}
            </button>
          )}
          {(docTranslationRunning || docHasActiveTask) && (
            <div className="w-28 h-2 rounded-full bg-surface-container overflow-hidden border border-outline-variant">
              <div className="h-full bg-secondary transition-all duration-300" style={{ width: `${docTranslationProgress}%` }} />
            </div>
          )}
          {(docTranslationRunning || docHasActiveTask) && (
            <span className="text-[11px] font-mono text-on-surface-variant">{docTranslationProgress}%</span>
          )}
          {!!docTranslationStatus && (
            <span className="text-[11px] text-on-surface-variant max-w-[220px] truncate" title={docTranslationStatus}>
              {docTranslationStatus}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {(mode === 'edit' || mode === 'live-preview') && (
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
            <div ref={readScrollRef} className="flex-1 overflow-y-auto p-6">
              <div className="max-w-[800px] mx-auto">
                <div
                  onClick={(evt) => {
                    const rawTarget = evt.target;
                    const elem = rawTarget instanceof Element ? rawTarget : ((rawTarget as Node | null)?.parentElement || null);
                    const copyBtn = elem?.closest('[data-code-copy]') as HTMLElement | null;
                    if (copyBtn) {
                      const pre = copyBtn.closest('.code-block-header')?.nextElementSibling;
                      const code = pre?.querySelector('code');
                      if (code) {
                        navigator.clipboard.writeText(code.textContent || '').then(() => {
                          copyBtn.textContent = 'Copied!';
                          copyBtn.classList.add('copied');
                          setTimeout(() => { copyBtn.textContent = 'Copy'; copyBtn.classList.remove('copied'); }, 2000);
                        }).catch(() => {});
                      }
                      return;
                    }
                    const editBtn = elem?.closest('[data-reader-note-edit]') as HTMLElement | null;
                    if (editBtn) {
                      const idx = Number(editBtn.getAttribute('data-reader-note-edit') || '-1');
                      if (idx >= 0) void handleEditNoteByIndex(idx);
                      return;
                    }
                    const anchor = elem?.closest('a[href]') as HTMLAnchorElement | null;
                    if (anchor) {
                      const rawHref = anchor.getAttribute('data-original-href') || anchor.getAttribute('href') || '';
                      const path = resolveMarkdownLinkPath(rawHref, absolutePath)
                        || resolveMarkdownLinkPath(anchor.getAttribute('href') || '', absolutePath);
                      if (path) {
                        evt.preventDefault();
                        window.dispatchEvent(new CustomEvent('open-reader-file', { detail: { path, libraryId } }));
                        return;
                      }
                    }
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
        translationText={translationText}
        translationLoading={translationLoading}
        onClose={() => { setSelectionUI((p) => ({ ...p, visible: false, lineStart: -1, lineEnd: -1 })); }}
      />
    </div>
  );
}

