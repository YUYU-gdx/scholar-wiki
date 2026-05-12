/**
 * Live Preview ViewPlugin — uses CM6's built-in markdown syntax tree for
 * precise decoration positions, matching the editor's own parser exactly.
 * Non-standard syntax (math, callouts, ==highlight==, <sup>/<sub>) is
 * handled via targeted regex on text nodes.
 */
import { ViewPlugin, ViewUpdate, Decoration, DecorationSet, WidgetType } from '@codemirror/view';
import type { EditorView } from '@codemirror/view';
import { RangeSetBuilder } from '@codemirror/state';
import type { Text } from '@codemirror/state';
import { syntaxTree } from '@codemirror/language';
import katex from 'katex';

// ─── Widgets ────────────────────────────────────────────────────────────────

class KatexWidget extends WidgetType {
  constructor(private formula: string, private displayMode: boolean) { super(); }
  eq(other: KatexWidget) { return this.formula === other.formula && this.displayMode === other.displayMode; }
  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.className = this.displayMode ? 'katex-display-block' : 'katex-inline-block';
    try { katex.render(this.formula, span, { throwOnError: false, displayMode: this.displayMode, trust: true }); }
    catch { span.textContent = this.formula; }
    return span;
  }
  ignoreEvent() { return true; }
}

class ImageWidget extends WidgetType {
  constructor(private src: string, private alt: string) { super(); }
  eq(other: ImageWidget) { return this.src === other.src && this.alt === other.alt; }
  toDOM(): HTMLElement {
    const img = document.createElement('img');
    img.src = this.src;
    img.alt = this.alt;
    img.style.cssText = 'display:block;max-width:100%;max-height:400px;margin:0.5em 0;border-radius:8px;';
    return img;
  }
  ignoreEvent() { return true; }
}

class CheckboxWidget extends WidgetType {
  constructor(private checked: boolean) { super(); }
  eq(other: CheckboxWidget) { return this.checked === other.checked; }
  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.className = 'cm-live-checkbox';
    span.style.cssText = `display:inline-block;width:1em;height:1em;margin:0 0.3em;border:1.5px solid var(--color-outline);border-radius:3px;background:${this.checked ? 'var(--color-secondary)' : 'transparent'};vertical-align:-3px;position:relative;`;
    if (this.checked) span.innerHTML = '<span style="position:absolute;left:4px;top:1px;width:5px;height:9px;border:solid white;border-width:0 1.5px 1.5px 0;transform:rotate(45deg);"></span>';
    return span;
  }
  ignoreEvent() { return false; }
}

class HTMLTableWidget extends WidgetType {
  constructor(private html: string) { super(); }
  eq(other: HTMLTableWidget) { return this.html === other.html; }
  toDOM(): HTMLElement {
    const wrapper = document.createElement('div');
    wrapper.className = 'cm-live-html-table';
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(this.html, 'text/html');
      const table = doc.querySelector('table');
      if (table) {
        // Strip event handlers for safety
        table.querySelectorAll('*').forEach((el) => {
          Array.from(el.attributes).forEach((attr) => {
            if (attr.name.startsWith('on')) el.removeAttribute(attr.name);
          });
        });
        // Apply table styles
        table.style.cssText = 'width:100%;border-collapse:collapse;margin:1em 0;font-size:0.88em;';
        table.querySelectorAll('th, td').forEach((cell) => {
          (cell as HTMLElement).style.cssText = 'border:1px solid var(--color-outline-variant);padding:0.4em 0.6em;text-align:left;vertical-align:top;';
        });
        table.querySelectorAll('th').forEach((th) => {
          (th as HTMLElement).style.cssText += 'background:var(--color-surface-container-high);font-family:Inter,sans-serif;font-weight:600;';
        });
        table.querySelectorAll('tr:nth-child(even) td').forEach((td) => {
          (td as HTMLElement).style.backgroundColor = 'var(--color-surface-container-low)';
        });
        wrapper.appendChild(table);
      } else {
        wrapper.textContent = this.html;
      }
    } catch {
      wrapper.textContent = this.html;
    }
    return wrapper;
  }
  ignoreEvent() { return true; }
}

// ─── Plugin ─────────────────────────────────────────────────────────────────

const HEADING_SIZES: Record<number, string> = { 1: '1.8rem', 2: '1.45rem', 3: '1.2rem', 4: '1.05rem', 5: '0.95rem', 6: '0.85rem' };
const HEADING_WEIGHTS: Record<number, string> = { 1: '700', 2: '600', 3: '600', 4: '600', 5: '600', 6: '600' };

const CALLOUT_COLORS: Record<string, string> = {
  note: '#448aff', warning: '#ff9100', danger: '#ff5252', tip: '#00c853', info: '#00b8d4', example: '#9c27b0', quote: '#9e9e9e',
};
const CALLOUT_BG: Record<string, string> = {
  note: 'rgba(68,138,255,0.06)', warning: 'rgba(255,145,0,0.06)', danger: 'rgba(255,82,82,0.06)', tip: 'rgba(0,200,83,0.06)', info: 'rgba(0,184,212,0.06)', example: 'rgba(156,39,176,0.06)', quote: 'rgba(158,158,158,0.06)',
};

class LivePreviewView {
  decorations: DecorationSet;

  constructor(view: EditorView) {
    this.decorations = this.build(view);
  }

  update(update: ViewUpdate) {
    if (update.docChanged || update.viewportChanged) {
      this.decorations = this.build(update.view);
    }
  }

  build(view: EditorView): DecorationSet {
    const builder = new RangeSetBuilder<Decoration>();
    const doc = view.state.doc;
    const tree = syntaxTree(view.state);

    // Interval-based consumed tracking — O(ranges) instead of O(chars)
    const consumedRanges: Array<{ from: number; to: number }> = [];
    function isFree(from: number, to: number): boolean {
      for (const r of consumedRanges) {
        if (from < r.to && to > r.from) return false;
      }
      return true;
    }
    function consume(from: number, to: number) {
      consumedRanges.push({ from, to });
    }

    // Union visible ranges into a single span
    let visFrom = Infinity;
    let visTo = -Infinity;
    for (const { from, to } of view.visibleRanges) {
      if (from < visFrom) visFrom = from;
      if (to > visTo) visTo = to;
    }
    if (!isFinite(visFrom)) return builder.finish();

    // ── Phase 1: Walk syntax tree once ──
    tree.iterate({
      from: visFrom,
      to: visTo,
      enter: (ref) => {
          const node = ref.node;
          const typeName = node.type.name;

          // ── Block-level ──
          if (typeName.startsWith('ATXHeading') || typeName.startsWith('SetextHeading')) {
            const level = typeName.startsWith('ATX')
              ? Number(typeName.slice(-1))
              : typeName === 'SetextHeading1' ? 1 : 2;
            const headerMark = node.getChild('HeaderMark');
            const markEnd = headerMark ? headerMark.to : node.from + level;
            const spaceEnd = markEnd < node.to && doc.sliceString(markEnd, markEnd + 1) === ' ' ? markEnd + 1 : markEnd;
            if (isFree(node.from, spaceEnd)) {
              consume(node.from, spaceEnd);
              builder.add(node.from, spaceEnd, Decoration.replace({}));
            }
            if (isFree(spaceEnd, node.to)) {
              consume(spaceEnd, node.to);
              const border = level <= 2 ? 'border-bottom:1px solid var(--color-outline-variant);padding-bottom:0.3em;' : '';
              const extras = level === 5 ? 'color:var(--color-on-surface-variant);' : level === 6 ? 'text-transform:uppercase;letter-spacing:0.04em;color:var(--color-outline);' : '';
              builder.add(spaceEnd, node.to, Decoration.mark({
                attributes: {
                  style: `font-family:"Inter",sans-serif;font-size:${HEADING_SIZES[level]};font-weight:${HEADING_WEIGHTS[level]};line-height:1.25;letter-spacing:-0.02em;display:inline-block;width:100%;${border}${extras}`,
                },
              }));
            }
            return false; // don't descend into children
          }

          if (typeName === 'HorizontalRule') {
            if (isFree(node.from, node.to)) {
              consume(node.from, node.to);
              builder.add(node.from, node.to, Decoration.line({ attributes: { style: 'border-bottom:1px solid var(--color-outline-variant);' } }));
              builder.add(node.from, node.to, Decoration.replace({}));
            }
            return false;
          }

          if (typeName === 'FencedCode') {
            const info = node.getChild('CodeInfo');
            const lang = info ? doc.sliceString(info.from, info.to).trim() : '';
            // Find opening fence line and closing fence line
            const startLine = doc.lineAt(node.from);
            const endLine = doc.lineAt(node.to);
            // Hide opening fence
            if (isFree(startLine.from, startLine.to)) {
              consume(startLine.from, startLine.to);
              builder.add(startLine.from, startLine.to, Decoration.replace({}));
            }
            // Hide closing fence
            if (isFree(endLine.from, endLine.to)) {
              consume(endLine.from, endLine.to);
              builder.add(endLine.from, endLine.to, Decoration.replace({}));
            }
            // Style code content lines, skip opening fence
            for (let ln = startLine.number + 1; ln < endLine.number; ln++) {
              const l = doc.line(ln);
              if (!isFree(l.from, l.to)) continue;
              consume(l.from, l.to);
              builder.add(l.from, l.to, Decoration.line({ attributes: { style: 'background:#111318;' } }));
              builder.add(l.from, l.to, Decoration.mark({ attributes: { style: 'font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:0.88em;color:#e9edf8;' } }));
            }
            // Language label on opening fence line
            if (lang) {
              builder.add(startLine.from, startLine.from, Decoration.widget({
                widget: new CodeLangWidget(lang),
                side: 1,
              }));
            }
            return false;
          }

          if (typeName === 'CodeBlock') {
            // Indented code block
            for (let ln = doc.lineAt(node.from).number; ln <= doc.lineAt(node.to).number; ln++) {
              const l = doc.line(ln);
              if (!isFree(l.from, l.to)) continue;
              consume(l.from, l.to);
              builder.add(l.from, l.to, Decoration.line({ attributes: { style: 'background:#111318;' } }));
              builder.add(l.from, l.to, Decoration.mark({ attributes: { style: 'font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:0.88em;color:#e9edf8;' } }));
              // Hide 4-space indent
              const indentEnd = l.from + 4;
              if (isFree(l.from, indentEnd)) {
                consume(l.from, indentEnd);
                builder.add(l.from, indentEnd, Decoration.replace({}));
              }
            }
            return false;
          }

          if (typeName === 'Blockquote') {
            // Check if callout
            const firstLine = doc.lineAt(node.from);
            const ctMatch = firstLine.text.match(/^\s*>\s*\[!(\w+)\]\s*(.*)$/);
            const isCallout = !!ctMatch;
            const ctType = ctMatch?.[1]?.toLowerCase() || 'note';

            for (let ln = doc.lineAt(node.from).number; ln <= doc.lineAt(node.to).number; ln++) {
              const l = doc.line(ln);
              const isFirst = ln === doc.lineAt(node.from).number;
              if (!isFree(l.from, l.to)) continue;
              consume(l.from, l.to);

              if (isCallout) {
                const color = CALLOUT_COLORS[ctType] || CALLOUT_COLORS.note;
                const bg = CALLOUT_BG[ctType] || CALLOUT_BG.note;
                builder.add(l.from, l.to, Decoration.line({ attributes: { style: `border-left:4px solid ${color};background:${bg};padding-left:0.75em;font-size:0.92em;` } }));
                // Hide `> [!TYPE] ` prefix on first line
                if (isFirst && ctMatch) {
                  const prefixLen = ctMatch[0].length;
                  const prefixEnd = l.from + firstLine.text.indexOf(ctMatch[0]) + prefixLen;
                  if (isFree(l.from, prefixEnd)) {
                    consume(l.from, prefixEnd);
                    builder.add(l.from, prefixEnd, Decoration.replace({}));
                  }
                  // Title styling
                  const restText = firstLine.text.slice(firstLine.text.indexOf(ctMatch[0]) + prefixLen);
                  if (restText.trim()) {
                    const restFrom = prefixEnd;
                    if (isFree(restFrom, l.to)) {
                      consume(restFrom, l.to);
                      builder.add(restFrom, l.to, Decoration.mark({ attributes: { style: 'font-family:"Inter",sans-serif;font-weight:600;font-size:0.9em;' } }));
                    }
                  }
                } else {
                  // Hide leading `> ` in body lines
                  const gtIdx = l.text.search(/>\s?/);
                  if (gtIdx >= 0) {
                    const gtEnd = l.from + gtIdx + (l.text[gtIdx + 1] === ' ' ? 2 : 1);
                    if (isFree(l.from, gtEnd)) {
                      consume(l.from, gtEnd);
                      builder.add(l.from, gtEnd, Decoration.replace({}));
                    }
                  }
                }
              } else {
                // Regular blockquote
                builder.add(l.from, l.to, Decoration.line({ attributes: { style: 'border-left:3px solid var(--color-outline-variant);background:var(--color-surface-container-low);border-radius:0 8px 8px 0;padding-left:0.75em;' } }));
                const gtIdx = l.text.search(/>\s?/);
                if (gtIdx >= 0) {
                  const gtEnd = l.from + gtIdx + (l.text[gtIdx + 1] === ' ' ? 2 : 1);
                  if (isFree(l.from, gtEnd)) {
                    consume(l.from, gtEnd);
                    builder.add(l.from, gtEnd, Decoration.replace({}));
                  }
                }
              }
            }
            return false;
          }

          if (typeName === 'Table') {
            // Style entire table
            const firstLineNum = doc.lineAt(node.from).number;
            for (let ln = firstLineNum; ln <= doc.lineAt(node.to).number; ln++) {
              const l = doc.line(ln);
              if (!isFree(l.from, l.to)) continue;
              consume(l.from, l.to);
              const relLine = ln - firstLineNum;
              if (relLine === 0) {
                // Header row
                builder.add(l.from, l.to, Decoration.line({ attributes: { style: 'font-weight:600;background:var(--color-surface-container-high);' } }));
              } else if (relLine === 1) {
                // Alignment row — hide it
                builder.add(l.from, l.to, Decoration.replace({}));
              } else if (relLine % 2 === 0) {
                builder.add(l.from, l.to, Decoration.line({ attributes: { style: 'background:var(--color-surface-container-low);' } }));
              }
              // Hide | separators
              const pipeRe = /\|/g;
              let pm: RegExpExecArray | null;
              while ((pm = pipeRe.exec(l.text)) !== null) {
                const absPos = l.from + pm.index;
                if (isFree(absPos, absPos + 1)) {
                  consume(absPos, absPos + 1);
                  builder.add(absPos, absPos + 1, Decoration.replace({}));
                }
              }
            }
            return false;
          }

          if (typeName === 'TaskMarker') {
            if (isFree(node.from, node.to)) {
              consume(node.from, node.to);
              const text = doc.sliceString(node.from, node.to);
              const checked = /\[[xX]\]/.test(text);
              builder.add(node.from, node.to, Decoration.widget({ widget: new CheckboxWidget(checked) }));
            }
            return false;
          }

          if (typeName === 'HTMLBlock') {
            if (isFree(node.from, node.to)) {
              const html = doc.sliceString(node.from, node.to);
              // If it's a <table>, render it as a styled widget
              if (/<table[\s>]/i.test(html)) {
                consume(node.from, node.to);
                builder.add(node.from, node.to, Decoration.widget({ widget: new HTMLTableWidget(html), block: true }));
              } else {
                // Dim other raw HTML blocks
                consume(node.from, node.to);
                builder.add(node.from, node.to, Decoration.mark({ attributes: { style: 'opacity:0.45;font-size:0.85em;' } }));
              }
            }
            return false;
          }

          // ── Inline ──
          if (typeName === 'StrongEmphasis') {
            // marker is ** or __ (2 chars each side)
            const text = doc.sliceString(node.from, node.to);
            const markerLen = (text.startsWith('**') || text.startsWith('__')) ? 2 : 2;
            if (isFree(node.from, node.from + markerLen)) {
              consume(node.from, node.from + markerLen);
              builder.add(node.from, node.from + markerLen, Decoration.replace({}));
            }
            if (isFree(node.to - markerLen, node.to)) {
              consume(node.to - markerLen, node.to);
              builder.add(node.to - markerLen, node.to, Decoration.replace({}));
            }
            if (isFree(node.from + markerLen, node.to - markerLen)) {
              consume(node.from + markerLen, node.to - markerLen);
              builder.add(node.from + markerLen, node.to - markerLen, Decoration.mark({ attributes: { style: 'font-weight:700;' } }));
            }
          }

          if (typeName === 'Emphasis') {
            const text = doc.sliceString(node.from, node.to);
            const firstChar = text[0];
            const markerLen = (firstChar === '*' || firstChar === '_') ? 1 : 1;
            if (isFree(node.from, node.from + markerLen)) {
              consume(node.from, node.from + markerLen);
              builder.add(node.from, node.from + markerLen, Decoration.replace({}));
            }
            if (isFree(node.to - markerLen, node.to)) {
              consume(node.to - markerLen, node.to);
              builder.add(node.to - markerLen, node.to, Decoration.replace({}));
            }
            if (isFree(node.from + markerLen, node.to - markerLen)) {
              consume(node.from + markerLen, node.to - markerLen);
              builder.add(node.from + markerLen, node.to - markerLen, Decoration.mark({ attributes: { style: 'font-style:italic;' } }));
            }
          }

          if (typeName === 'Strikethrough') {
            const ml = 2; // ~~ on each side
            if (isFree(node.from, node.from + ml)) { consume(node.from, node.from + ml); builder.add(node.from, node.from + ml, Decoration.replace({})); }
            if (isFree(node.to - ml, node.to)) { consume(node.to - ml, node.to); builder.add(node.to - ml, node.to, Decoration.replace({})); }
            if (isFree(node.from + ml, node.to - ml)) { consume(node.from + ml, node.to - ml); builder.add(node.from + ml, node.to - ml, Decoration.mark({ attributes: { style: 'text-decoration:line-through;' } })); }
          }

          if (typeName === 'InlineCode') {
            const text = doc.sliceString(node.from, node.to);
            const backtickMatch = text.match(/^(`+)/);
            const bl = backtickMatch ? backtickMatch[1].length : 1;
            if (isFree(node.from, node.from + bl)) { consume(node.from, node.from + bl); builder.add(node.from, node.from + bl, Decoration.replace({})); }
            if (isFree(node.to - bl, node.to)) { consume(node.to - bl, node.to); builder.add(node.to - bl, node.to, Decoration.replace({})); }
            if (isFree(node.from + bl, node.to - bl)) {
              consume(node.from + bl, node.to - bl);
              builder.add(node.from + bl, node.to - bl, Decoration.mark({ attributes: { style: 'font-family:"JetBrains Mono","Fira Code",Consolas,monospace;font-size:0.88em;background:var(--color-surface-container-low);border:1px solid var(--color-outline-variant);border-radius:4px;padding:0.15em 0.4em;' } }));
            }
          }

          if (typeName === 'Link') {
            // [text](url) — hide [, ], (url); style text
            const urlNode = node.getChild('URL');
            const linkText = node.getChild('LinkText');
            // Hide opening [
            if (isFree(node.from, node.from + 1)) { consume(node.from, node.from + 1); builder.add(node.from, node.from + 1, Decoration.replace({})); }
            // Hide ](url)
            if (urlNode) {
              const closeStart = urlNode.from - 1; // the ] before (url)
              if (isFree(closeStart, urlNode.to)) { consume(closeStart, urlNode.to); builder.add(closeStart, urlNode.to, Decoration.replace({})); }
            }
            // Style link text
            const textFrom = node.from + 1;
            const textTo = urlNode ? urlNode.from - 1 : node.to - 1;
            if (textTo > textFrom && isFree(textFrom, textTo)) {
              consume(textFrom, textTo);
              builder.add(textFrom, textTo, Decoration.mark({ attributes: { style: 'color:var(--color-secondary);text-decoration:underline;text-underline-offset:2px;' } }));
            }
          }

          if (typeName === 'Image') {
            if (isFree(node.from, node.to)) {
              consume(node.from, node.to);
              const urlNode = node.getChild('URL');
              const src = urlNode ? doc.sliceString(urlNode.from, urlNode.to) : '';
              // Alt text is between ![ and ]( — i.e. from node.from+2 to url/] position
              const altTo = urlNode ? urlNode.from - 1 : node.to - 1;
              const altFrom = node.from + 2;
              const alt = altTo > altFrom ? doc.sliceString(altFrom, altTo) : '';
              builder.add(node.from, node.to, Decoration.widget({ widget: new ImageWidget(src, alt) }));
            }
          }
        },
    });

    // ── Phase 2: Regex for non-standard syntax (math, highlight, sup/sub, wiki links, footnotes) ──
    const startLine = doc.lineAt(visFrom);
    const endLine = doc.lineAt(visTo);
    for (let ln = startLine.number; ln <= endLine.number; ln++) {
        const line = doc.line(ln);
        const text = line.text;
        if (!isFree(line.from, line.to)) continue; // skip if already fully consumed

        // Math $...$ (inline, single dollar)
        const mathInlineRe = /(?<!\\)\$([^$]+?)(?<!\\)\$/g;
        let mm: RegExpExecArray | null;
        while ((mm = mathInlineRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          builder.add(absFrom, absTo, Decoration.widget({ widget: new KatexWidget(mm[1], false) }));
        }

        // Math $$...$$ (display, single-line)
        const mathDisplayRe = /(?<!\\)\$\$(.+?)(?<!\\)\$\$/g;
        while ((mm = mathDisplayRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          builder.add(absFrom, absTo, Decoration.widget({ widget: new KatexWidget(mm[1], true), block: true }));
        }

        // ==highlight==
        const markRe = /(?<!\\)==(.+?)(?<!\\)==/g;
        while ((mm = markRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          const contentFrom = absFrom + 2;
          const contentTo = absTo - 2;
          if (isFree(absFrom, absFrom + 2)) { consume(absFrom, absFrom + 2); builder.add(absFrom, absFrom + 2, Decoration.replace({})); }
          if (isFree(absTo - 2, absTo)) { consume(absTo - 2, absTo); builder.add(absTo - 2, absTo, Decoration.replace({})); }
          if (isFree(contentFrom, contentTo)) { consume(contentFrom, contentTo); builder.add(contentFrom, contentTo, Decoration.mark({ attributes: { style: 'background:rgba(255,235,59,0.35);padding:0.1em 0;border-radius:2px;' } })); }
        }

        // Wiki link [[...]]
        const wikiRe = /(?<!\\)\[\[(.+?)(?<!\\)\]\]/g;
        while ((mm = wikiRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          // Hide [[ and ]]
          builder.add(absFrom, absFrom + 2, Decoration.replace({}));
          builder.add(absTo - 2, absTo, Decoration.replace({}));
          consume(absFrom + 2, absFrom + 2); // re-mark consumed after replace
          consume(absTo - 2, absTo);
          builder.add(absFrom + 2, absTo - 2, Decoration.mark({ attributes: { style: 'color:var(--color-secondary);text-decoration:underline;text-underline-offset:2px;cursor:pointer;' } }));
        }

        // HTML <sup>...</sup>
        const supRe = /<sup>(.+?)<\/sup>/gi;
        while ((mm = supRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          builder.add(absFrom, absFrom + 5, Decoration.replace({}));
          builder.add(absTo - 6, absTo, Decoration.replace({}));
          builder.add(absFrom + 5, absTo - 6, Decoration.mark({ attributes: { style: 'font-size:0.75em;vertical-align:super;line-height:0;' } }));
        }

        // HTML <sub>...</sub>
        const subRe = /<sub>(.+?)<\/sub>/gi;
        while ((mm = subRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          builder.add(absFrom, absFrom + 5, Decoration.replace({}));
          builder.add(absTo - 6, absTo, Decoration.replace({}));
          builder.add(absFrom + 5, absTo - 6, Decoration.mark({ attributes: { style: 'font-size:0.75em;vertical-align:sub;line-height:0;' } }));
        }

        // Footnote reference [^...]
        const fnRe = /(?<!\\)\[\^([^\]]+)\]/g;
        while ((mm = fnRe.exec(text)) !== null) {
          const absFrom = line.from + mm.index;
          const absTo = line.from + mm.index + mm[0].length;
          if (!isFree(absFrom, absTo)) continue;
          consume(absFrom, absTo);
          builder.add(absFrom, absTo, Decoration.mark({ attributes: { style: 'font-size:0.82em;vertical-align:super;color:var(--color-secondary);cursor:pointer;' } }));
        }
      }

    return builder.finish();
  }
}

class CodeLangWidget extends WidgetType {
  constructor(private lang: string) { super(); }
  eq(other: CodeLangWidget) { return this.lang === other.lang; }
  toDOM(): HTMLElement {
    const span = document.createElement('span');
    span.textContent = this.lang;
    span.style.cssText = 'display:inline-block;padding:2px 10px;font-size:10px;font-family:Inter,sans-serif;color:#8b949e;text-transform:uppercase;letter-spacing:0.04em;background:#1a1d26;border-radius:4px;';
    return span;
  }
  ignoreEvent() { return true; }
}

export const livePreviewPlugin = ViewPlugin.fromClass(LivePreviewView, { decorations: (v) => v.decorations });
