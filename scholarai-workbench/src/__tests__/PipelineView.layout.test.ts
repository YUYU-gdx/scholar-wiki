import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('PipelineView task list layout', () => {
  it('gives the import task table enough vertical room before scrolling', () => {
    const source = readFileSync(resolve(__dirname, '../components/PipelineView.tsx'), 'utf8');

    expect(source).not.toContain('max-h-[50vh] overflow-y-auto');
    expect(source).toContain('min-h-[520px]');
  });
});
