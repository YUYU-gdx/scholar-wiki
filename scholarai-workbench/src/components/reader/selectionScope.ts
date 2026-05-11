export function isSelectionInside(container: HTMLElement | null, selection: Selection | null): boolean {
  if (!container || !selection || selection.rangeCount <= 0) return false;
  const range = selection.getRangeAt(0);
  const anchor = range.commonAncestorContainer;
  const element = anchor instanceof Element ? anchor : anchor.parentElement;
  if (!element) return false;
  return container.contains(element);
}

