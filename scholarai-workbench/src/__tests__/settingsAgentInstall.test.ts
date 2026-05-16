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

  it('includes the merged agent test result as separate dialog checks', () => {
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
    expect(rows.test.detail).toBe('0/1 项通过');
    expect(rows.test.checks[0].name).toBe('auth');
    expect(rows.test.canRun).toBe(true);
  });

  it('keeps non-duplicate agent test checks as separate visible rows', () => {
    const rows = buildAgentInstallRows({
      agent: { displayName: 'Claude Code', binary: 'claude', installCommand: 'npm install -g @anthropic-ai/claude-code' },
      detection: {
        node: { installed: true, path: 'node.exe', version: 'v22.0.0' },
        npm: { installed: true, path: 'npm.cmd', version: '10.9.0' },
        agent: { installed: false, path: '', version: '' },
      },
      testResult: {
        ok: false,
        checked_at: '2026-05-16T00:00:00.000Z',
        checks: [
          { name: 'cli_installed', passed: false, stage: 'cli_check', error: 'binary_not_found' },
          { name: 'workspace_claude_md', passed: true, stage: 'workspace_config' },
          { name: 'workspace_mcp_json', passed: false, stage: 'workspace_config', error: 'mcp_json_missing' },
          { name: 'agent_config_file', passed: true, stage: 'agent_config' },
          { name: 'claude_agent_sdk', passed: false, stage: 'sdk_check', suggestion: 'install sdk' },
        ],
      },
      busyAction: '',
    });

    expect(rows.test.checks.map((check) => check.name)).toEqual([
      'workspace_claude_md',
      'workspace_mcp_json',
      'agent_config_file',
      'claude_agent_sdk',
    ]);
    expect(rows.test.detail).toBe('2/4 项通过');
    expect(rows.test.status).toBe('failed');
  });
});
