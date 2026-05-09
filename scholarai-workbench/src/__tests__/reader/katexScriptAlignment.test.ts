import { describe, expect, it } from 'vitest';
import { JSDOM } from 'jsdom';
import MarkdownIt from 'markdown-it';
import markdownItKatex from '@vscode/markdown-it-katex';
import { convertScriptOnlyKatexToHtml } from '../../components/reader/katexScriptAlignment';

function renderWithKatex(markdown: string): Document {
  const md = new MarkdownIt({ html: true }).use(markdownItKatex);
  const html = md.render(markdown);
  const dom = new JSDOM(`<!doctype html><html><body>${html}</body></html>`);
  return dom.window.document;
}

describe('convertScriptOnlyKatexToHtml', () => {
  it('converts bare superscript to native sup', () => {
    const doc = renderWithKatex('Xia Li $^{1}$ | Timothy Simcoe ${}^{1,2}$');
    convertScriptOnlyKatexToHtml(doc);
    expect(doc.body.querySelectorAll('sup').length).toBe(2);
    expect(doc.body.textContent).toContain('Xia Li 1 | Timothy Simcoe 1,2');
  });

  it('converts bare subscript to native sub', () => {
    const doc = renderWithKatex('a $_{2}$ and b ${}_{i}$');
    convertScriptOnlyKatexToHtml(doc);
    expect(doc.body.querySelectorAll('sub').length).toBe(2);
  });

  it('keeps normal math formula untouched', () => {
    const doc = renderWithKatex('$\\mathrm{CO}_{2}$ and $1236_{2}^{2}$');
    convertScriptOnlyKatexToHtml(doc);
    expect(doc.body.querySelectorAll('span.katex').length).toBe(2);
    expect(doc.body.querySelectorAll('sup').length).toBe(0);
    expect(doc.body.querySelectorAll('sub').length).toBe(0);
  });

  it('keeps native html sup/sub untouched', () => {
    const doc = renderWithKatex('Questrom<sup>1</sup> test<sub>2</sub>');
    convertScriptOnlyKatexToHtml(doc);
    expect(doc.body.querySelectorAll('sup').length).toBe(1);
    expect(doc.body.querySelectorAll('sub').length).toBe(1);
  });
});
