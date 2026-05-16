import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Electron production data paths', () => {
  it('uses the canonical libraries/workspaces directory for packaged backend workspaces', () => {
    const source = readFileSync(resolve(__dirname, '../../electron/main.cjs'), 'utf8');

    expect(source).not.toContain('path.join(dataDir, "workspaces")');
    expect(source).toContain('path.join(dataDir, "libraries", "workspaces")');
  });
});
