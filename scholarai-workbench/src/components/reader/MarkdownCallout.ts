export const READER_NOTE_CALLOUT_TYPE = 'NOTE';
export const READER_NOTE_CALLOUT_TITLE = 'Reader Note';
export const TRANSLATION_CALLOUT_TYPE = 'TRANSLATION';
export const TRANSLATION_CALLOUT_TITLE = '译文';

const CALLOUT_ICONS: Record<string, string> = {
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="#448aff" stroke-width="2" style="width:100%;height:100%"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="#ff9100" stroke-width="2" style="width:100%;height:100%"><path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>',
  danger: '<svg viewBox="0 0 24 24" fill="none" stroke="#ff5252" stroke-width="2" style="width:100%;height:100%"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  tip: '<svg viewBox="0 0 24 24" fill="none" stroke="#00c853" stroke-width="2" style="width:100%;height:100%"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="#00b8d4" stroke-width="2" style="width:100%;height:100%"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  example: '<svg viewBox="0 0 24 24" fill="none" stroke="#9c27b0" stroke-width="2" style="width:100%;height:100%"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>',
  quote: '<svg viewBox="0 0 24 24" fill="#9e9e9e" style="width:100%;height:100%"><path d="M6 17h3l2-4V7H5v6h3zm8 0h3l2-4V7h-6v6h3z"/></svg>',
  translation: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:100%;height:100%"><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/></svg>',
};

const CALLOUT_LABELS: Record<string, string> = {
  note: 'Note',
  warning: 'Warning',
  danger: 'Danger',
  tip: 'Tip',
  info: 'Info',
  example: 'Example',
  quote: 'Quote',
  translation: TRANSLATION_CALLOUT_TITLE,
};

const CALLOUT_COLORS: Record<string, string> = {
  note: '#448aff',
  warning: '#ff9100',
  danger: '#ff5252',
  tip: '#00c853',
  info: '#00b8d4',
  example: '#9c27b0',
  quote: '#9e9e9e',
  translation: '#15803d',
};

const CALLOUT_BG: Record<string, string> = {
  note: 'rgba(68,138,255,0.08)',
  warning: 'rgba(255,145,0,0.08)',
  danger: 'rgba(255,82,82,0.08)',
  tip: 'rgba(0,200,83,0.08)',
  info: 'rgba(0,184,212,0.08)',
  example: 'rgba(156,39,176,0.08)',
  quote: 'rgba(158,158,158,0.08)',
  translation: 'rgba(34,197,94,0.045)',
};

export function getMarkdownCalloutStyle(type: string): { color: string; background: string } {
  const normalized = String(type || '').trim().toLowerCase();
  return {
    color: CALLOUT_COLORS[normalized] || CALLOUT_COLORS.note,
    background: CALLOUT_BG[normalized] || CALLOUT_BG.note,
  };
}

export function quoteMarkdownCalloutLines(lines: string[]): string {
  return lines.map((line) => (line ? `> ${line}` : '>')).join('\n');
}

export function buildMarkdownCallout(type: string, title: string, bodyLines: string[]): string {
  const header = `> [!${String(type || '').trim().toUpperCase()}] ${String(title || '').trim()}`.trimEnd();
  const body = quoteMarkdownCalloutLines(bodyLines);
  return body ? `${header}\n${body}` : header;
}

function splitCalloutTitleAndInlineBody(type: string, rest: string): { title: string; inlineBody: string } {
  const normalizedType = String(type || '').trim().toLowerCase();
  const raw = String(rest || '').trim();
  const fallbackTitle = CALLOUT_LABELS[normalizedType] || normalizedType;
  if (normalizedType !== 'translation') {
    return { title: raw || fallbackTitle, inlineBody: '' };
  }
  const label = TRANSLATION_CALLOUT_TITLE;
  if (!raw) return { title: label, inlineBody: '' };
  if (raw === label) return { title: label, inlineBody: '' };
  if (raw.startsWith(`${label} `)) {
    return { title: label, inlineBody: raw.slice(label.length).trim() };
  }
  return { title: raw, inlineBody: '' };
}

export function transformCallouts(doc: Document): void {
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

    const { title, inlineBody } = splitCalloutTitleAndInlineBody(type, rest);

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

    if (inlineBody) {
      const bodyP = doc.createElement('p');
      bodyP.textContent = inlineBody;
      callout.appendChild(bodyP);
    }

    while (bq.firstChild) {
      callout.appendChild(bq.firstChild);
    }

    const parent = bq.parentNode;
    if (parent) {
      parent.replaceChild(callout, bq);
    }
  }
}
