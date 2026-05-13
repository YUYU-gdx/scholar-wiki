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
import { deleteNoteFromMarkdownAny, extractNoteBlocks, readMarkdownText } from './NoteMarkdownSync';

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

// ---- Callout icons (inline SVG) ----
const CALLOUT_ICONS: Record<string, string> = {
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="#448aff" stroke-width="2" style="width:100%;height:100%"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="#ff9100" stroke-width="2" style="width:100%;height:100%"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>',
  danger: '<svg viewBox="0 0 24 24" fill="none" stroke="#ff5252" stroke-width="2" style="width:100%;height:100%"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  tip: '<svg viewBox="0 0 24 24" fill="none" stroke="#00c853" stroke-width="2" style="width:100%;height:100%"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="#00b8d4" stroke-width="2" style="width:100%;height:100%"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  example: '<svg viewBox="0 0 24 24" fill="none" stroke="#9c27b0" stroke-width="2" style="width:100%;height:100%"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>',
  quote: '<svg viewBox="0 0 24 24" fill="#9e9e9e" style="width:100%;height:100%"><path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z"/></svg>',
};

const CALLOUT_LABELS: Record<string, string> = {
  note: 'Note', warning: 'Warning', danger: 'Danger', tip: 'Tip',
  info: 'Info', example: 'Example', quote: 'Quote',
};

function transformCallouts(doc: Document): void {
  const blockquotes = Array.from(doc.querySelectorAll('blockquote'));
  for (const bq of blockquotes) {
    const firstP = bq.querySelector(':scope > p:first-child');
    if (!firstP) continue;
    const text = (firstP.textContent || '').trim();
    const m = text.match(/^\[!(\w+)\]\s*(.*)$/);
    if (!m) continue;
    const type = m[1].toLowerCase();
    const rest = m[2].trim();
    const icon = CALLOUT_ICONS[type];
    if (!icon) continue;

    const label = CALLOUT_LABELS[type] || type;
    const title = rest || label;

    firstP.remove();

    const callout = doc.createElement('div');
    callout.className = `callout callout-${type}`;

    const iconSpan = doc.createElement('span');
    iconSpan.className = 'callout-icon';
    iconSpan.innerHTML = icon;
    callout.appendChild(iconSpan);

    const titleDiv = doc.createElement('div');
    titleDiv.className = 'callout-title';
    titleDiv.textContent = title;
    callout.appendChild(titleDiv);

    while (bq.firstChild) {
      callout.appendChild(bq.firstChild);
    }

    const parent = bq.parentNode;
    if (parent) {
      parent.replaceChild(callout, bq);
    }
  }
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
  const [noteRanges, setNoteRanges] = useState<Array<{ start: number; end: number; id: string; quote: string; note: string }>>([]);
  const flashTimerRef = useRef<number | null>(null);

  // CM6 refs
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const selectionHostRef = useRef<HTMLDivElement>(null);
  const readScrollRef = useRef<HTMLDivElement>(null);
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

  // Reset read-mode scroll for newly opened markdown files.
  useEffect(() => {
    const el = readScrollRef.current;
    if (!el) return;
    el.scrollTop = 0;
    el.scrollLeft = 0;
  }, [absolutePath]);

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
      const lines = String(x.text || '').replace(/\r\n/g, '\n').split('\n').map((ln) => ln.replace(/^\s*>\s?/, '').trimEnd());
      let mode: '' | 'quote' | 'note' = '';
      const quoteLines: string[] = [];
      const noteLines: string[] = [];
      for (const rawLine of lines) {
        const line = String(rawLine || '').trim();
        if (!line) continue;
        if (/^Quote:\s*$/i.test(line)) { mode = 'quote'; continue; }
        if (/^Note:\s*$/i.test(line)) { mode = 'note'; continue; }
        if (/^Time:\s*/i.test(line)) { mode = ''; continue; }
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
      convertScriptOnlyKatexToHtml(doc);
      transformCallouts(doc);
      highlightCodeBlocks(doc);
      enhanceCodeBlocks(doc);
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
      // Primary: matched callouts that were transformed from [!NOTE] Reader Note
      for (const callout of Array.from(doc.querySelectorAll('.callout-note'))) {
        const titleEl = callout.querySelector('.callout-title');
        const titleText = String(titleEl?.textContent || '').trim();
        if (titleText !== 'Reader Note') continue;
        // Keep metadata in markdown source, but hide Rect/Quads in rendered reader UI.
        for (const p of Array.from(callout.querySelectorAll('p'))) {
          const t = String(p.textContent || '').trim();
          if (/^(Rect|Quads):/i.test(t)) p.remove();
        }
        const idx = noteIdx;
        const noteId = notes[idx]?.id || '';
        noteIdx += 1;
        callout.setAttribute('data-reader-note-idx', String(idx));
        callout.setAttribute('style', 'position:relative;');
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
          // focusLineEnd is in a distant block — ignore, use anchorBlockEnd as cap
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
        const submit = await api.chat.submitTranslateJob(currentContentRef.current, cfg);
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

    // ── Direct file write ──
    if (!sh || sh.runtime !== 'electron' || !absolutePath) {
      window.alert('文件写入不可用（非Electron环境）');
      setTimeout(() => {
        setSelectionUI((p) => ({ ...p, visible: false, lineStart: -1, lineEnd: -1 }));
      }, 600);
      return;
    }

    try {
      // Read current file content
      // eslint-disable-next-line no-console
      console.log('[notes] reading file...', absolutePath);
      let read = await sh.readLocalText(absolutePath);
      // eslint-disable-next-line no-console
      console.log('[notes] read result', { ok: read.ok, dataLen: read.data?.length, error: read.error });

      if (!read.ok) {
        // File doesn't exist or can't be read — create new
        const init = `## Reader Notes\n\n`;
        const created = await sh.writeLocalText(absolutePath, init);
        // eslint-disable-next-line no-console
        console.log('[notes] create new file', { ok: created.ok, error: created.error });
        if (!created.ok) {
          throw new Error(`创建文件失败: ${created.error || 'unknown'}`);
        }
        read = { ok: true, data: init };
      }

      // Build note block
      const now = new Date().toISOString();
      const block = `\n\n> [!NOTE] Reader Note\n> Note ID: ${noteId}\n> Quote:\n> ${picked}\n>\n> Note:\n> ${noteText}\n>\n> Time:\n> ${now}\n`;
      const src = String(read.data || '').replace(/\r\n/g, '\n');

      // Find insertion position: prefer text match (robust), fall back to line-based
      let insertAt = src.length;
      const lineEnd = selectionUI.lineEnd;
      // Try exact text match first — works regardless of DOM selection quirks
      const textIdx = src.indexOf(picked);
      if (textIdx >= 0) {
        const after = src.slice(textIdx + picked.length);
        const nl = after.indexOf('\n');
        insertAt = nl >= 0 ? textIdx + picked.length + nl : textIdx + picked.length;
      } else if (lineEnd >= 0) {
        // Fallback: insert after the line where selection ends
        const lines = src.split('\n');
        const targetLine = Math.max(0, Math.min(lineEnd, lines.length - 1));
        let offset = 0;
        for (let i = 0; i <= targetLine; i++) {
          offset += lines[i].length + 1;
        }
        insertAt = Math.min(offset, src.length);
      }
      console.log('[notes] insert position', { textIdx, lineEnd, insertAt, srcLen: src.length, method: textIdx >= 0 ? 'text-match' : 'line-based' });

      const next = insertAt < src.length
        ? `${src.slice(0, insertAt)}${block}${src.slice(insertAt)}`
        : (src.includes('## Reader Notes') ? `${src}${block}` : `${src}\n\n## Reader Notes${block}`);

      // eslint-disable-next-line no-console
      console.log('[notes] writing file...', { srcLen: src.length, nextLen: next.length });
      const wr = await sh.writeLocalText(absolutePath, next);
      // eslint-disable-next-line no-console
      console.log('[notes] write result', { ok: wr.ok, error: wr.error });

      if (!wr.ok) {
        throw new Error(`写入文件失败: ${wr.error || 'unknown'}`);
      }

      // Verify
      const verify = await sh.readLocalText(absolutePath);
      const markerFound = verify.ok && String(verify.data || '').includes(`> Note ID: ${noteId}`);
      // eslint-disable-next-line no-console
      console.log('[notes] verify', { ok: verify.ok, markerFound });

      if (!markerFound) {
        throw new Error('写入验证失败：回读文件未找到笔记标记');
      }

      // Update state
      const latest = String(verify.data || '').replace(/\r\n/g, '\n');
      setText(latest);
      onContentChange?.(latest);
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

  // CM6 theme for live preview — matches Read mode typography
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
              onClick={handleTranslateWholeDocument}
              disabled={docTranslationRunning}
              title="全文段落对照翻译"
            >
              全文对照翻译
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
