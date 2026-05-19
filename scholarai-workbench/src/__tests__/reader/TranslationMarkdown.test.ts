import { describe, expect, it } from 'vitest';
import { hasTranslationBlocks, removeTranslationBlocks } from '../../components/reader/TranslationMarkdown';

describe('translation markdown helpers', () => {
  it('detects translation callout blocks in markdown', () => {
    expect(hasTranslationBlocks('# Title\n\n> [!TRANSLATION] \u8bd1\u6587\n> Body')).toBe(true);
    expect(hasTranslationBlocks('# Title\n\n<span class="translation-label">\u3010\u8bd1\u6587\u3011</span>: Body')).toBe(true);
    expect(hasTranslationBlocks('# Title\n\n> [!NOTE] Reader Note\n> Body')).toBe(false);
  });

  it('removes all translation callout blocks while preserving other markdown blocks', () => {
    const source = [
      '# Title',
      '',
      'Original paragraph.',
      '',
      '> [!TRANSLATION] \u8bd1\u6587',
      '> \u7ffb\u8bd1\u6bb5\u843d\u4e00\u3002',
      '',
      '> [!NOTE] Reader Note',
      '>',
      '> Note ID: n1',
      '',
      'Second paragraph.',
      '',
      '> [!TRANSLATION] \u8bd1\u6587 \u7ffb\u8bd1\u6bb5\u843d\u4e8c\u3002',
      '',
    ].join('\n');

    expect(removeTranslationBlocks(source)).toBe([
      '# Title',
      '',
      'Original paragraph.',
      '',
      '> [!NOTE] Reader Note',
      '>',
      '> Note ID: n1',
      '',
      'Second paragraph.',
    ].join('\n'));
  });

  it('removes legacy standalone translation paragraphs', () => {
    const source = [
      'Original paragraph.',
      '',
      '<span class="translation-label">\u3010\u8bd1\u6587\u3011</span>: Legacy translated paragraph.',
      '',
      'Next paragraph.',
      '',
      '\u8bd1\u6587\uff1aAnother translated paragraph.',
    ].join('\n');

    expect(removeTranslationBlocks(source)).toBe([
      'Original paragraph.',
      '',
      'Next paragraph.',
    ].join('\n'));
  });
});
