export type InstallProbe = {
  installed: boolean;
  path?: string;
  version?: string;
};

export type AgentInstallDetection = {
  node: InstallProbe;
  npm: InstallProbe;
  agent: InstallProbe;
};

export type AgentInstallInfo = {
  displayName: string;
  binary: string;
  installCommand: string;
  notAvailable?: boolean;
};

export type AgentInstallTestCheck = {
  name: string;
  passed: boolean;
  stage: string;
  suggestion?: string;
  error?: string;
};

export type AgentInstallTestResult = {
  ok: boolean;
  checked_at?: string;
  checks: AgentInstallTestCheck[];
} | null;

export type AgentInstallBusyAction = '' | 'detect' | 'install_node' | 'install_agent' | 'test';
export type AgentInstallRowStatus = 'unknown' | 'installed' | 'missing' | 'running' | 'failed' | 'unsupported';

export type AgentInstallCheckRow = {
  name: string;
  label: string;
  status: AgentInstallRowStatus;
  detail: string;
  stage: string;
};

export type AgentInstallRows = {
  node: {
    status: AgentInstallRowStatus;
    detail: string;
    canInstall: boolean;
    installCommand: string;
  };
  agent: {
    status: AgentInstallRowStatus;
    detail: string;
    canInstall: boolean;
    installCommand: string;
    disabledReason: string;
  };
  test: {
    status: AgentInstallRowStatus;
    detail: string;
    canRun: boolean;
    checks: AgentInstallCheckRow[];
  };
};

const NODE_INSTALL_COMMAND = 'winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements';
const DUPLICATE_TEST_CHECKS = new Set(['cli_installed']);
const CHECK_LABELS: Record<string, string> = {
  workspace_claude_md: '工作区说明文件',
  workspace_mcp_json: 'MCP 配置',
  agent_config_file: 'Agent 配置文件',
  claude_agent_sdk: 'Claude SDK',
};

function probeDetail(label: string, probe: InstallProbe): string {
  if (!probe.installed) return label + ' 未检测到';
  const version = String(probe.version || '').trim();
  const path = String(probe.path || '').trim();
  return [version ? label + ' ' + version : label + ' 已安装', path].filter(Boolean).join(' | ');
}

function buildVisibleTestChecks(testResult: AgentInstallTestResult): AgentInstallCheckRow[] {
  if (!testResult) return [];
  return testResult.checks
    .filter((check) => !DUPLICATE_TEST_CHECKS.has(check.name))
    .map((check) => ({
      name: check.name,
      label: CHECK_LABELS[check.name] || check.name,
      status: check.passed ? 'installed' : 'failed',
      detail: check.error || check.suggestion || (check.passed ? '通过' : '未通过'),
      stage: check.stage,
    }));
}

export function buildAgentInstallRows(args: {
  agent: AgentInstallInfo;
  detection: AgentInstallDetection | null;
  testResult: AgentInstallTestResult;
  busyAction: AgentInstallBusyAction;
}): AgentInstallRows {
  const { agent, detection, testResult, busyAction } = args;
  const hasNode = Boolean(detection?.node?.installed);
  const hasNpm = Boolean(detection?.npm?.installed);
  const hasAgent = Boolean(detection?.agent?.installed);
  const nodeReady = hasNode && hasNpm;
  const unsupported = Boolean(agent.notAvailable || !agent.binary || !agent.installCommand);

  const nodeRunning = busyAction === 'detect' || busyAction === 'install_node';
  const agentRunning = busyAction === 'detect' || busyAction === 'install_agent';
  const testRunning = busyAction === 'test';

  const visibleChecks = buildVisibleTestChecks(testResult);
  const failedVisible = visibleChecks.filter((check) => check.status === 'failed').length;
  const passedVisible = visibleChecks.length - failedVisible;
  const testDetail = testResult
    ? visibleChecks.length
      ? passedVisible + '/' + visibleChecks.length + ' 项通过'
      : 'CLI 检测已在上方展示，无额外测试项'
    : hasAgent
      ? 'Agent CLI 已就绪，可运行测试'
      : '安装 Agent 后可运行测试';

  return {
    node: {
      status: nodeRunning ? 'running' : nodeReady ? 'installed' : 'missing',
      detail: detection ? probeDetail('Node.js', detection.node) + '; ' + probeDetail('npm', detection.npm) : '等待检测',
      canInstall: !nodeRunning && !nodeReady,
      installCommand: NODE_INSTALL_COMMAND,
    },
    agent: {
      status: unsupported ? 'unsupported' : agentRunning ? 'running' : hasAgent ? 'installed' : 'missing',
      detail: unsupported
        ? (agent.displayName || '当前 Agent') + ' 暂不支持安装'
        : detection
          ? probeDetail(agent.displayName || agent.binary || 'Agent', detection.agent)
          : '等待检测',
      canInstall: !unsupported && !agentRunning && !hasAgent && nodeReady,
      installCommand: agent.installCommand,
      disabledReason: unsupported
        ? '暂不支持安装'
        : nodeReady
          ? ''
          : '请先安装 Node.js / npm',
    },
    test: {
      status: testRunning ? 'running' : testResult ? (failedVisible > 0 ? 'failed' : 'installed') : 'unknown',
      detail: testDetail,
      canRun: !testRunning && hasAgent,
      checks: visibleChecks,
    },
  };
}
