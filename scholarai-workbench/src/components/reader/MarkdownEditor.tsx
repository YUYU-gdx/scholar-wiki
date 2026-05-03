import { useState, useRef, useEffect, useMemo } from 'react';
import MarkdownIt from 'markdown-it';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTaskLists from 'markdown-it-task-lists';
import markdownItMark from 'markdown-it-mark';
import markdownItDeflist from 'markdown-it-deflist';
import markdownItKatex from 'markdown-it-katex';
import DOMPurify from 'dompurify';
import 'katex/dist/katex.min.css';
import type { ViewerMode } from './types';

interface MarkdownEditorProps {
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setText(content);
  }, [content]);

  useEffect(() => {
    if (!absolutePath || window.desktopShell?.runtime !== 'electron') return;
    const timer = window.setTimeout(async () => {
      await window.desktopShell?.writeLocalText(absolutePath, text);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [text, absolutePath]);

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
          'colspan', 'rowspan', 'align',
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
      if (!cancelled) setRenderedHtml(doc.body.innerHTML);
    };
    run();
    return () => { cancelled = true; };
  }, [absolutePath, md, text]);

  const renderMarkdown = () => (
    <div className="reader-markdown">
      <div
        dangerouslySetInnerHTML={{
          __html: renderedHtml,
        }}
      />
    </div>
  );

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
            {renderMarkdown()}
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
              {renderMarkdown()}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
