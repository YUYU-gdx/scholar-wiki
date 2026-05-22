import MarkdownIt from 'markdown-it';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTaskLists from 'markdown-it-task-lists';
import markdownItMark from 'markdown-it-mark';
import markdownItDeflist from 'markdown-it-deflist';
import markdownItKatex from '@vscode/markdown-it-katex';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import 'katex/dist/katex.min.css';
import { convertScriptOnlyKatexToHtml } from '../reader/katexScriptAlignment';
import { sanitizeMarkdownBeforeRender } from '../reader/MarkdownRenderSanitizer';
import { transformCallouts } from '../reader/MarkdownCallout';
import {
  LOCAL_MARKDOWN_ALLOWED_URI_REGEXP,
  fileUrlToPath,
  toFileUrl,
  validateReaderMarkdownLink,
} from '../reader/readerLinks';

export type MarkdownRenderProfile = 'chat' | 'document';

export interface MarkdownRenderOptions {
  profile?: MarkdownRenderProfile;
  absolutePath?: string;
  sourceLines?: boolean;
  callouts?: boolean;
  codeEnhancements?: boolean;
  resolveLocalResources?: boolean;
}

const ALLOWED_TAGS = [
  'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'strong', 'em', 's', 'mark', 'u', 'sub', 'sup',
  'blockquote', 'code', 'pre', 'span', 'div',
  'ul', 'ol', 'li', 'input', 'label',
  'table', 'caption', 'colgroup', 'col', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
  'a', 'img', 'details', 'summary', 'dl', 'dt', 'dd',
];

const ALLOWED_ATTR = [
  'href', 'src', 'alt', 'title', 'target', 'rel',
  'class', 'id', 'type', 'checked', 'disabled',
  'colspan', 'rowspan', 'align', 'style',
  'data-src-line-start', 'data-src-line-end', 'data-original-href',
];

function optionEnabled(value: boolean | undefined, fallback: boolean): boolean {
  return value === undefined ? fallback : value;
}

export function createMarkdownRenderer(options: MarkdownRenderOptions = {}): MarkdownIt {
  const profile = options.profile || 'chat';
  const sourceLines = optionEnabled(options.sourceLines, profile === 'document');
  const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
    breaks: profile === 'chat',
  });
  md.validateLink = validateReaderMarkdownLink;
  md
    .use(markdownItFootnote)
    .use(markdownItTaskLists, { enabled: true, label: true })
    .use(markdownItMark)
    .use(markdownItDeflist)
    .use(markdownItKatex);

  if (sourceLines) {
    const openRules = ['paragraph_open', 'heading_open', 'blockquote_open', 'list_item_open'];
    for (const ruleName of openRules) {
      const base = md.renderer.rules[ruleName];
      md.renderer.rules[ruleName] = (tokens, idx, renderOptions, env, self) => {
        const token = tokens[idx];
        const map = token.map || null;
        if (map && map.length >= 2) {
          token.attrSet('data-src-line-start', String(map[0]));
          token.attrSet('data-src-line-end', String(Math.max(map[0], map[1] - 1)));
        }
        return base ? base(tokens, idx, renderOptions, env, self) : self.renderToken(tokens, idx, renderOptions);
      };
    }
  }

  return md;
}

function guessMimeByPath(path: string): string {
  const lower = String(path || '').toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.gif')) return 'image/gif';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.svg')) return 'image/svg+xml';
  if (lower.endsWith('.bmp')) return 'image/bmp';
  return 'application/octet-stream';
}

function resolveLocalResourceUrl(raw: string, markdownAbsolutePath = ''): string {
  const value = String(raw || '').trim();
  if (!value) return value;
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:') || value.startsWith('blob:') || value.startsWith('#')) {
    return value;
  }
  const mdPath = String(markdownAbsolutePath || '');
  if (!mdPath) return value;
  const mdDir = mdPath.replace(/[\\/][^\\/]*$/, '');
  let rel = value;
  if (value.startsWith('/paper/') && value.includes('/asset?')) {
    try {
      const url = new URL(value, 'http://localhost');
      const relPath = url.searchParams.get('rel_path');
      if (relPath) rel = relPath;
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

function highlightCodeBlocks(doc: Document): void {
  for (const code of Array.from(doc.querySelectorAll('pre > code'))) {
    const className = code.className || '';
    const lang = className.match(/language-(\w+)/)?.[1] || '';
    if (!lang || !hljs.getLanguage(lang)) continue;
    try {
      const raw = code.textContent || '';
      const result = hljs.highlight(raw, { language: lang, ignoreIllegals: true });
      code.innerHTML = result.value;
      code.className = `${className} hljs`;
    } catch {
      // leave unhighlighted
    }
  }
}

function enhanceCodeBlocks(doc: Document): void {
  for (const pre of Array.from(doc.querySelectorAll('pre'))) {
    const code = pre.querySelector(':scope > code');
    const lang = code?.className.match(/language-(\w+)/)?.[1] || '';
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

    pre.parentNode?.insertBefore(header, pre);
  }
}

function sanitizeRenderedHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOWED_URI_REGEXP: LOCAL_MARKDOWN_ALLOWED_URI_REGEXP,
  });
}

function postProcessHtml(html: string, options: MarkdownRenderOptions): Document {
  const profile = options.profile || 'chat';
  const doc = new DOMParser().parseFromString(html, 'text/html');
  convertScriptOnlyKatexToHtml(doc);
  if (optionEnabled(options.callouts, profile === 'document')) {
    transformCallouts(doc);
  }
  if (optionEnabled(options.codeEnhancements, profile === 'document')) {
    highlightCodeBlocks(doc);
    enhanceCodeBlocks(doc);
  }
  return doc;
}

export function renderMarkdownToHtmlSync(source: string, options: MarkdownRenderOptions = {}): string {
  const md = createMarkdownRenderer(options);
  const safeSource = sanitizeMarkdownBeforeRender(String(source || ''));
  const clean = sanitizeRenderedHtml(md.render(safeSource));
  const doc = postProcessHtml(clean, options);
  return doc.body.innerHTML;
}

export async function renderMarkdownToHtml(source: string, options: MarkdownRenderOptions = {}): Promise<string> {
  const profile = options.profile || 'chat';
  const resolveResources = optionEnabled(options.resolveLocalResources, profile === 'document');
  const doc = postProcessHtml(
    sanitizeRenderedHtml(createMarkdownRenderer(options).render(sanitizeMarkdownBeforeRender(String(source || '')))),
    options,
  );
  if (!resolveResources) return doc.body.innerHTML;

  const absolutePath = String(options.absolutePath || '');
  const rewriteAttr = async (el: Element, key: 'src' | 'href') => {
    const raw = el.getAttribute(key);
    if (!raw) return;
    if (key === 'href') el.setAttribute('data-original-href', raw);
    let next = resolveLocalResourceUrl(raw, absolutePath);
    if (window.desktopShell?.runtime === 'electron' && absolutePath && !next.startsWith('http://') && !next.startsWith('https://') && !next.startsWith('data:') && !next.startsWith('blob:') && !next.startsWith('file://')) {
      const resolved = await window.desktopShell.resolveLocalAsset(absolutePath, raw);
      if (resolved?.ok && resolved.path) next = toFileUrl(resolved.path);
    }
    if (window.desktopShell?.runtime === 'electron' && absolutePath && next.startsWith('file://')) {
      const relTry = raw.startsWith('file://') ? '' : raw;
      if (relTry) {
        const resolved = await window.desktopShell.resolveLocalAsset(absolutePath, relTry);
        if (resolved?.ok && resolved.path) next = toFileUrl(resolved.path);
      }
    }
    if (key === 'src' && next.startsWith('file://') && window.desktopShell?.runtime === 'electron') {
      const localPath = fileUrlToPath(next);
      if (localPath) {
        const read = await window.desktopShell.readLocalFile(localPath);
        if (read?.ok && read.data) {
          next = `data:${guessMimeByPath(localPath)};base64,${read.data}`;
        }
      }
    }
    el.setAttribute(key, next);
  };

  await Promise.all(Array.from(doc.querySelectorAll('img')).map((el) => rewriteAttr(el, 'src')));
  await Promise.all(Array.from(doc.querySelectorAll('a')).map((el) => rewriteAttr(el, 'href')));
  return doc.body.innerHTML;
}
