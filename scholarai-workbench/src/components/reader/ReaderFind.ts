export interface ReaderFindMatch {
  index: number;
  mark: HTMLElement;
}

const MATCH_CLASS = 'reader-find-match';
const ACTIVE_CLASS = 'reader-find-active';
const SKIP_SELECTOR = [
  'script',
  'style',
  'textarea',
  'input',
  'select',
  'button',
  'mark.reader-find-match',
  '[aria-hidden="true"]',
  '[hidden]',
].join(',');

function normalizeQuery(query: string): string {
  return String(query || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

export function clearReaderFindMarks(root: HTMLElement | null): void {
  if (!root) return;
  const marks = Array.from(root.querySelectorAll(`mark.${MATCH_CLASS}`));
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    parent.replaceChild(document.createTextNode(mark.textContent || ''), mark);
    parent.normalize();
  }
}

function textNodes(root: HTMLElement): Text[] {
  const out: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (parent.closest(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT;
      if (!String(node.nodeValue || '').trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let node = walker.nextNode();
  while (node) {
    out.push(node as Text);
    node = walker.nextNode();
  }
  return out;
}

export function highlightReaderFindMatches(root: HTMLElement | null, query: string): ReaderFindMatch[] {
  if (!root) return [];
  clearReaderFindMarks(root);
  const q = normalizeQuery(query);
  if (!q) return [];

  const matches: ReaderFindMatch[] = [];
  for (const node of textNodes(root)) {
    const raw = node.nodeValue || '';
    const lower = raw.toLowerCase();
    let cursor = 0;
    let at = lower.indexOf(q, cursor);
    if (at < 0) continue;

    const fragment = document.createDocumentFragment();
    while (at >= 0) {
      if (at > cursor) fragment.appendChild(document.createTextNode(raw.slice(cursor, at)));
      const mark = document.createElement('mark');
      mark.className = MATCH_CLASS;
      mark.textContent = raw.slice(at, at + q.length);
      fragment.appendChild(mark);
      matches.push({ index: matches.length, mark });
      cursor = at + q.length;
      at = lower.indexOf(q, cursor);
    }
    if (cursor < raw.length) fragment.appendChild(document.createTextNode(raw.slice(cursor)));
    node.parentNode?.replaceChild(fragment, node);
  }
  return matches;
}

export function setActiveReaderFindMatch(matches: ReaderFindMatch[], activeIndex: number): void {
  for (const match of matches) {
    match.mark.classList.toggle(ACTIVE_CLASS, match.index === activeIndex);
  }
  const active = matches[activeIndex]?.mark;
  active?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
}

export function findFirstRenderedTextBlock(root: HTMLElement | null, queries: string[]): HTMLElement | null {
  if (!root) return null;
  const candidates = queries.map(normalizeQuery).filter(Boolean);
  if (!candidates.length) return null;
  const nodes = Array.from(root.querySelectorAll('p,li,blockquote,td,th,h1,h2,h3,h4,h5,h6')) as HTMLElement[];
  return nodes.find((node) => {
    const text = String(node.textContent || '').replace(/\s+/g, ' ').toLowerCase();
    return candidates.some((q) => text.includes(q));
  }) || null;
}
