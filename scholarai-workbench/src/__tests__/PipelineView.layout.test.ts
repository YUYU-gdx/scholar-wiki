import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('PipelineView task list layout', () => {
  it('allows the import task table to scroll within the available viewport height', () => {
    const source = readFileSync(resolve(__dirname, '../components/PipelineView.tsx'), 'utf8');

    expect(source).not.toContain('max-h-[50vh] overflow-y-auto');
    expect(source).not.toContain('min-h-[520px] max-h-[calc(100vh-260px)] overflow-y-auto');
    expect(source).toContain('min-h-0 max-h-[calc(100vh-260px)] overflow-y-auto');
  });
});
