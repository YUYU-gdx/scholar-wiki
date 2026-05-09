export function convertScriptOnlyKatexToHtml(doc: Document): void {
  const katexNodes = Array.from(doc.querySelectorAll('span.katex'));
  for (const node of katexNodes) {
    const ann = node.querySelector('.katex-mathml annotation');
    const tex = String(ann?.textContent || '').trim();

    const supOnly = tex.match(/^(?:\{\})?\^\{([^{}\n]+)\}$/);
    if (supOnly) {
      const sup = doc.createElement('sup');
      sup.textContent = supOnly[1];
      node.replaceWith(sup);
      continue;
    }

    const subOnly = tex.match(/^(?:\{\})?_\{([^{}\n]+)\}$/);
    if (subOnly) {
      const sub = doc.createElement('sub');
      sub.textContent = subOnly[1];
      node.replaceWith(sub);
      continue;
    }

    const subSup = tex.match(/^(?:\{\})?_\{([^{}\n]+)\}\^\{([^{}\n]+)\}$/);
    if (subSup) {
      const frag = doc.createDocumentFragment();
      const sub = doc.createElement('sub');
      sub.textContent = subSup[1];
      const sup = doc.createElement('sup');
      sup.textContent = subSup[2];
      frag.appendChild(sub);
      frag.appendChild(sup);
      node.replaceWith(frag);
    }
  }
}
