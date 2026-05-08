import { CompletionContext, CompletionResult } from '@codemirror/autocomplete';
import { Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType } from '@codemirror/view';
import { RangeSetBuilder } from '@codemirror/state';

// === Completion source for [[ ===

let cachedNodes: Array<{ id: string; label: string }> = [];

export function setWikiLinkNodeCache(nodes: Array<{ id: string; label: string }>) {
  cachedNodes = nodes;
}

export function wikiLinkCompletionSource(context: CompletionContext): CompletionResult | null {
  const before = context.matchBefore(/\[\[([^\]]*)$/);
  if (!before) return null;

  const query = before.text.slice(2).toLowerCase();
  const options: Array<{ label: string; type: string; detail: string }> = [];

  for (const node of cachedNodes) {
    const label = (node.label || node.id).toLowerCase();
    if (label.includes(query) && options.length < 20) {
      options.push({ label: `[[${node.label || node.id}]]`, type: 'variable', detail: `KG: ${node.id}` });
    }
  }

  if (query.includes('/') || query.includes('\\') || query.includes('.')) {
    options.push({ label: `[[${before.text.slice(2)}]]`, type: 'file', detail: 'local file' });
  }

  if (query.startsWith('@')) {
    options.push({ label: `[[${before.text.slice(2)}]]`, type: 'paper', detail: 'paper reference' });
  }

  return {
    from: before.from,
    options: options.slice(0, 20),
    filter: false,
  };
}

// === Decoration: render [[link]] as styled links ===

class WikiLinkWidget extends WidgetType {
  constructor(readonly text: string, readonly target: string, readonly onNavigate: (target: string) => void) {
    super();
  }

  eq(other: WikiLinkWidget) {
    return other.target === this.target && other.text === this.text;
  }

  toDOM() {
    const span = document.createElement('span');
    span.className = 'wiki-link';
    span.textContent = this.text;
    span.style.cssText = 'color: #2563eb; cursor: pointer; text-decoration: underline; text-underline-offset: 2px;';
    span.title = this.target;
    span.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.onNavigate(this.target);
    });
    return span;
  }
}

const wikiLinkRegex = /\[\[([^\]]+)\]\]/g;

function wikiLinkDecoration(view: EditorView, onNavigate: (target: string) => void): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const text = view.state.doc.toString();
  let match: RegExpExecArray | null;

  wikiLinkRegex.lastIndex = 0;
  while ((match = wikiLinkRegex.exec(text)) !== null) {
    const fullMatch = match[0];
    const inner = match[1];
    const displayText = inner.includes('|') ? inner.split('|')[1] : inner;
    const linkTarget = inner.includes('|') ? inner.split('|')[0] : inner;
    const from = match.index;
    const to = from + fullMatch.length;

    builder.add(from, to, Decoration.replace({
      widget: new WikiLinkWidget(displayText, linkTarget, onNavigate),
      inclusive: false,
    }));
  }

  return builder.finish();
}

export const wikiLinkPlugin = (onNavigate: (target: string) => void) =>
  ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = wikiLinkDecoration(view, onNavigate);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = wikiLinkDecoration(update.view, onNavigate);
      }
    }
  }, {
    decorations: v => v.decorations,
  });
