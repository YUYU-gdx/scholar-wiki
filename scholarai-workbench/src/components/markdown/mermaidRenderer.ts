let mermaidInitialized = false;

export async function renderMermaidDiagrams(root: ParentNode | null): Promise<void> {
  if (!root) return;
  const nodes = Array.from(root.querySelectorAll('.mermaid:not([data-processed="true"])'))
    .filter((node): node is HTMLElement => node instanceof HTMLElement);
  if (!nodes.length) return;

  const mermaid = (await import('mermaid')).default;
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'default',
    });
    mermaidInitialized = true;
  }

  for (const node of nodes) {
    try {
      await mermaid.run({ nodes: [node] });
    } catch (error) {
      node.setAttribute('data-mermaid-error', String((error as Error)?.message || error || 'render_failed'));
    }
  }
}
