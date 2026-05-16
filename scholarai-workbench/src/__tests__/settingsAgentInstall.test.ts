import { describe, expect, it } from 'vitest';
import { buildAgentInstallRows } from '../components/settingsAgentInstall';

describe('settings agent install dialog state', () => {
  it('disables agent installation until Node.js and npm are available', () => {
    const rows = buildAgentInstallRows({
      agent: { displayName: 'Codex', binary: 'codex', installCommand: 'npm install -g @openai/codex' },
      detection: {
        node: { installed: false, path: '', version: '' },
        npm: { installed: false, path: '', version: '' },
        agent: { installed: false, path: '', version: '' },
      },
      testResult: null,
      busyAction: '',
    });

    expect(rows.node.status).toBe('missing');
    expect(rows.node.canInstall).toBe(true);
    expect(rows.agent.status).toBe('missing');
    expect(rows.agent.canInstall).toBe(false);
    expect(rows.agent.disabledReason).toBe('请先安装 Node.js / npm');
  });

  it('enables agent installation when Node.js and npm are detected', () => {
    const rows = buildAgentInstallRows({
      agent: { displayName: 'Claude Code', binary: 'claude', installCommand: 'npm install -g @anthropic-ai/claude-code' },
      detection: {
        node: { installed: true, path: 'C:/Program Files/nodejs/node.exe', version: 'v22.0.0' },
        npm: { installed: true, path: 'C:/Program Files/nodejs/npm.cmd', version: '10.9.0' },
        agent: { installed: false, path: '', version: '' },
      },
      testResult: null,
      busyAction: '',
    });

    expect(rows.node.status).toBe('installed');
    expect(rows.node.canInstall).toBe(false);
    expect(rows.agent.status).toBe('missing');
    expect(rows.agent.canInstall).toBe(true);
    expect(rows.agent.installCommand).toBe('npm install -g @anthropic-ai/claude-code');
  });

  it('includes the merged agent test result as a dialog row', () => {
    const rows = buildAgentInstallRows({
      agent: { displayName: 'Codex', binary: 'codex', installCommand: 'npm install -g @openai/codex' },
      detection: {
        node: { installed: true, path: 'node.exe', version: 'v22.0.0' },
        npm: { installed: true, path: 'npm.cmd', version: '10.9.0' },
        agent: { installed: true, path: 'codex.cmd', version: '0.55.0' },
      },
      testResult: {
        ok: false,
        checked_at: '2026-05-16T00:00:00.000Z',
        checks: [{ name: 'auth', passed: false, stage: 'auth', error: 'missing_api_key' }],
      },
      busyAction: '',
    });

    expect(rows.test.status).toBe('failed');
    expect(rows.test.detail).toContain('auth');
    expect(rows.test.canRun).toBe(true);
  });
});
