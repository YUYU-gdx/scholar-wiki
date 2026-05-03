import { useState, useRef, useEffect } from 'react';
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

  const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
    breaks: false,
  })
    .use(markdownItFootnote)
    .use(markdownItTaskLists, { enabled: true, label: true })
    .use(markdownItMark)
    .use(markdownItDeflist)
    .use(markdownItKatex);

  const renderMarkdown = (value: string) => (
    <div className="reader-markdown">
      <div
        dangerouslySetInnerHTML={{
          __html: (() => {
            const clean = DOMPurify.sanitize(md.render(value), {
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
            });
            const parser = new DOMParser();
            const doc = parser.parseFromString(clean, 'text/html');
            const rewrite = (raw: string): string => {
              const s = String(raw || '').trim();
              if (!s || s.startsWith('http://') || s.startsWith('https://') || s.startsWith('data:') || s.startsWith('blob:') || s.startsWith('#')) {
                return s;
              }
              const base = absolutePath ? absolutePath.replace(/[\\/][^\\/]*$/, '') : '';
              const normalized = s.replace(/\\/g, '/');
              const joined = `${base.replace(/\\/g, '/')}/${normalized}`.replace(/\/+/g, '/');
              return `file:///${encodeURI(joined)}`;
            };
            for (const img of Array.from(doc.querySelectorAll('img'))) {
              const src = img.getAttribute('src');
              if (src) img.setAttribute('src', rewrite(src));
            }
            for (const a of Array.from(doc.querySelectorAll('a'))) {
              const href = a.getAttribute('href');
              if (href) a.setAttribute('href', rewrite(href));
            }
            return doc.body.innerHTML;
          })(),
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
            {renderMarkdown(text)}
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
              {renderMarkdown(text)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
