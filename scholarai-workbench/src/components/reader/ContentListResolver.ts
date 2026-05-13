/**
 * Loads and queries mineru content_list_v2.json for PDF↔markdown position mapping.
 */

export interface ContentBlock {
  type: string;
  text: string;
  bbox: number[];
}

const cache = new Map<string, ContentBlock[][]>();

function norm(s: string): string {
  return String(s || '').replace(/\s+/g, ' ').trim();
}

export function extractBlockText(block: Record<string, unknown>): string {
  if (typeof block.text === 'string') return block.text;
  const content = (block.content || {}) as Record<string, unknown>;
  for (const key of Object.keys(content)) {
    if (key.endsWith('_content') && Array.isArray(content[key])) {
      return (content[key] as Array<{ content?: string }>)
        .map((c) => String(c?.content || ''))
        .join('');
    }
  }
  return '';
}

export async function loadContentList(jsonPath: string): Promise<ContentBlock[][]> {
  if (cache.has(jsonPath)) return cache.get(jsonPath)!;

  const shell = window.desktopShell;
  if (!shell || shell.runtime !== 'electron') return [];

  const result = await shell.readLocalText(jsonPath);
  if (!result.ok || !result.data) return [];

  try {
    const raw = JSON.parse(result.data);
    const pages: ContentBlock[][] = (raw as Array<Array<Record<string, unknown>>>).map((page) =>
      (page || []).map((block) => ({
        type: String(block.type || ''),
        text: extractBlockText(block),
        bbox: (block.bbox || []) as number[],
      })),
    );
    cache.set(jsonPath, pages);
    return pages;
  } catch {
    return [];
  }
}

/**
 * Find which blocks on a page are touched by a text selection.
 * Returns the inclusive [startIdx, endIdx] range, or null if not found.
 */
export function findTouchedBlocks(
  pageBlocks: ContentBlock[],
  selectedText: string,
): { startIdx: number; endIdx: number } | null {
  if (pageBlocks.length === 0 || !selectedText.trim()) return null;

  const texts = pageBlocks.map((b) => norm(b.text));
  const parts: string[] = [];
  const charToBlock: number[] = [];

  for (let i = 0; i < texts.length; i++) {
    if (texts[i].length === 0) continue;
    if (parts.length > 0) {
      parts.push(' ');
      charToBlock.push(-1);
    }
    parts.push(texts[i]);
    for (let j = 0; j < texts[i].length; j++) {
      charToBlock.push(i);
    }
  }

  const fullText = parts.join('');
  const ns = norm(selectedText);
  if (!ns) return null;

  let matchStart = fullText.indexOf(ns);

  // fallback: try shorter prefixes / suffixes
  if (matchStart < 0) {
    const prefix = ns.slice(0, Math.min(50, ns.length));
    matchStart = fullText.indexOf(prefix);
  }
  if (matchStart < 0) {
    const suffix = ns.slice(-Math.min(50, ns.length));
    matchStart = fullText.indexOf(suffix);
  }
  if (matchStart < 0) return null;

  const matchEnd = matchStart + ns.length - 1;

  let startBlock = -1;
  for (let i = matchStart; i < charToBlock.length && startBlock < 0; i++) {
    if (charToBlock[i] >= 0) startBlock = charToBlock[i];
  }

  let endBlock = -1;
  for (let i = Math.min(matchEnd, charToBlock.length - 1); i >= 0 && endBlock < 0; i--) {
    if (charToBlock[i] >= 0) endBlock = charToBlock[i];
  }

  if (startBlock < 0 || endBlock < 0) return null;
  return { startIdx: startBlock, endIdx: endBlock };
}

/** Get concatenated quote text and the anchor (last block's text). */
export function getBlocksQuote(
  pageBlocks: ContentBlock[],
  startIdx: number,
  endIdx: number,
): { quote: string; anchor: string } {
  const texts = pageBlocks.slice(startIdx, endIdx + 1).map((b) => b.text);
  return {
    quote: texts.join(' '),
    anchor: texts[texts.length - 1] || '',
  };
}

/**
 * Count how many times anchorText appears in all pages up to and including
 * the block at (pageIndex, blockIndex).
 */
export function countOccurrencesUpTo(
  allPages: ContentBlock[][],
  pageIndex: number,
  blockIndex: number,
  anchorText: string,
): number {
  const na = norm(anchorText);
  if (!na) return 0;

  let count = 0;
  for (let p = 0; p < allPages.length; p++) {
    const blocks = allPages[p];
    for (let b = 0; b < blocks.length; b++) {
      if (norm(blocks[b].text) === na) {
        count++;
      }
      if (p === pageIndex && b === blockIndex) {
        return count;
      }
    }
  }
  return count;
}
