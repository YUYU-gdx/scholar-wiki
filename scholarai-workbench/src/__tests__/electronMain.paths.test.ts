import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Electron production data paths', () => {
  it('uses the canonical libraries/workspaces directory for packaged backend workspaces', () => {
    const source = readFileSync(resolve(__dirname, '../../electron/main.cjs'), 'utf8');

    expect(source).not.toContain('path.join(dataDir, "workspaces")');
    expect(source).toContain('path.join(dataDir, "libraries", "workspaces")');
  });

  it('pins packaged backend storage env vars to the user data directory', () => {
    const source = readFileSync(resolve(__dirname, '../../electron/main.cjs'), 'utf8');

    expect(source).toContain('KN_GRAPH_DATA_DIR: dataDir');
    expect(source).toContain('KN_GRAPH_WORKSPACES_DIR: workspacesDir');
    expect(source).toContain('LITERATURE_LIBRARY_WORKSPACES_ROOT: workspacesDir');
  });

  it('defaults dev Electron to port 8013 while keeping packaged apps on 8014', () => {
    const source = readFileSync(resolve(__dirname, '../../electron/main.cjs'), 'utf8');

    expect(source).toContain('app.isPackaged ? 8014 : 8013');
  });
});
