import { describe, expect, it } from 'vitest';
import { sanitizeMarkdownBeforeRender } from '../../components/reader/MarkdownRenderSanitizer';

describe('sanitizeMarkdownBeforeRender', () => {
  it('escapes translated details tags so they cannot leave the rest of the paper collapsed', () => {
    const raw = [
      '<details>',
      '<summary>bar</summary>',
      '',
      '<span class="translation-label">【译文】</span>: <details>',
      '<summary>酒吧</summary>',
      '',
      '| Features | Value |',
      '| :--- | :--- |',
      '| AIW | 0.082 |',
      '</details>',
      '',
      '# IV. Results',
    ].join('\n');

    const sanitized = sanitizeMarkdownBeforeRender(raw);

    expect(sanitized).toContain('<details>');
    expect(sanitized).toContain('<summary>bar</summary>');
    expect(sanitized).toContain('<span class="translation-label">【译文】</span>: &lt;details&gt;');
    expect(sanitized).toContain('&lt;summary&gt;酒吧&lt;/summary&gt;');
    expect(sanitized).toContain('</details>\n\n# IV. Results');
  });

  it('leaves normal details blocks unchanged', () => {
    const raw = '<details>\n<summary>Appendix</summary>\n\nbody\n</details>';

    expect(sanitizeMarkdownBeforeRender(raw)).toBe(raw);
  });

  it('leaves translation callout blocks unchanged', () => {
    const raw = '> [!TRANSLATION] 译文\n> &lt;details&gt;\n> &lt;summary&gt;表格&lt;/summary&gt;';

    expect(sanitizeMarkdownBeforeRender(raw)).toBe(raw);
  });

  it('deindents html table blocks so markdown does not render them as code blocks', () => {
    const raw = [
      'Before',
      '',
      '    <table>',
      '      <thead>',
      '        <tr><th>Feature</th><th>Value</th></tr>',
      '      </thead>',
      '      <tbody>',
      '        <tr><td>AIW</td><td>0.082</td></tr>',
      '      </tbody>',
      '    </table>',
      '',
      '    const unchanged = true;',
    ].join('\n');

    const sanitized = sanitizeMarkdownBeforeRender(raw);

    expect(sanitized).toContain('<table>\n  <thead>');
    expect(sanitized).toContain('    <tr><th>Feature</th><th>Value</th></tr>');
    expect(sanitized).toContain('</table>');
    expect(sanitized).toContain('    const unchanged = true;');
  });
});
