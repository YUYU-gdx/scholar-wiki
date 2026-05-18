import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('PipelineView task list layout', () => {
  it('allows the import task table to scroll within the available viewport height', () => {
    const source = readFileSync(resolve(__dirname, '../components/PipelineView.tsx'), 'utf8');

    expect(source).not.toContain('max-h-[50vh] overflow-y-auto');
    expect(source).not.toContain('min-h-[520px] max-h-[calc(100vh-260px)] overflow-y-auto');
    expect(source).toContain('h-full min-h-0 flex-1 flex flex-col overflow-hidden');
    expect(source).toContain('flex-1 min-h-0 bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-hidden glass-shadow mb-4');
    expect(source).toContain('h-full min-h-0 overflow-y-auto');
  });

  it('keeps the task table header visible while scrolling rows', () => {
    const source = readFileSync(resolve(__dirname, '../components/PipelineView.tsx'), 'utf8');

    expect(source).toContain('<thead className="sticky top-0 z-20">');
    expect(source).toContain('bg-surface-container-lowest text-xs font-mono font-black text-outline uppercase tracking-widest border-b border-outline-variant');
  });
});
