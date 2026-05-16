import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { GlobalSettingsPayload } from '../types';

type SectionState = { saving: boolean; message: string };
type ProviderPreset = { id: string; name: string; base_url: string };
type AgentTemplateTarget = 'pipeline_skill' | 'qa_skill' | 'claude_md' | 'agent_md';
type AgentTemplateEditorState = {
  open: boolean;
  section: 'pipeline_agent' | 'agent_settings' | '';
  kind: 'skill' | 'md' | '';
  title: string;
  target: AgentTemplateTarget;
  loading: boolean;
  saving: boolean;
  content: string;
  path: string;
  message: string;
};
type InstallStepStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped';
type InstallStep = {
  key: 'precheck' | 'install_node' | 'install_claude' | 'postcheck';
  title: string;
  status: InstallStepStatus;
  detail: string;
};
const IMPORT_SECTION_IDS = new Set(['pipeline', 'pipeline_agent', 'embedding']);
const PROVIDER_KEY_GUIDE_URLS: Record<string, string> = {
  deepseek: 'https://platform.deepseek.com/api_keys',
  openai: 'https://platform.openai.com/api-keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
  gemini: 'https://aistudio.google.com/app/apikey',
  silicon: 'https://cloud.siliconflow.cn/account/ak',
  dashscope: 'https://dashscope.console.aliyun.com/apiKey',
  doubao: 'https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey',
  zhipu: 'https://open.bigmodel.cn/usercenter/apikeys',
  moonshot: 'https://platform.moonshot.cn/console/api-keys',
  minimax: 'https://platform.minimaxi.com/user-center/basic-information/interface-key',
  openrouter: 'https://openrouter.ai/keys',
  groq: 'https://console.groq.com/keys',
  ollama: 'https://ollama.com/',
  lmstudio: 'https://lmstudio.ai/',
  'new-api': 'https://github.com/Calcium-Ion/new-api',
};

const EMPTY_STATE: SectionState = { saving: false, message: '' };
const DEFAULT_PROVIDER_PRESETS: ProviderPreset[] = [
  { id: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com' },
  { id: 'openai', name: 'OpenAI', base_url: 'https://api.openai.com' },
  { id: 'anthropic', name: 'Anthropic', base_url: 'https://api.anthropic.com' },
  { id: 'gemini', name: 'Gemini', base_url: 'https://generativelanguage.googleapis.com' },
  { id: 'silicon', name: 'SiliconFlow', base_url: 'https://api.siliconflow.cn' },
  { id: 'dashscope', name: '阿里百炼', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1/' },
  { id: 'doubao', name: '豆包', base_url: 'https://ark.cn-beijing.volces.com/api/v3/' },
  { id: 'zhipu', name: '智谱', base_url: 'https://open.bigmodel.cn/api/paas/v4/' },
  { id: 'moonshot', name: 'Moonshot', base_url: 'https://api.moonshot.cn' },
  { id: 'minimax', name: 'MiniMax', base_url: 'https://api.minimaxi.com/v1/' },
  { id: 'openrouter', name: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1/' },
  { id: 'groq', name: 'Groq', base_url: 'https://api.groq.com/openai' },
  { id: 'ollama', name: 'Ollama', base_url: 'http://localhost:11434' },
  { id: 'lmstudio', name: 'LM Studio', base_url: 'http://localhost:1234' },
  { id: 'new-api', name: 'New API', base_url: 'http://localhost:3000' },
];

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function str(v: unknown): string { return String(v ?? ''); }
function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => String(v ?? '')).filter((v) => v.length > 0);
}
function getEffortOptions(values: Record<string, unknown>, backend: string): string[] {
  const effortOptionsMap = asRecord(values.reasoning_effort_options);
  return asStringArray(effortOptionsMap[backend]);
}
function asPresets(value: unknown): ProviderPreset[] {
  if (!Array.isArray(value)) return DEFAULT_PROVIDER_PRESETS;
  const rows = value.filter((x) => x && typeof x === 'object') as ProviderPreset[];
  return rows.length > 0 ? rows : DEFAULT_PROVIDER_PRESETS;
}
function providerKeyGuideUrl(provider: string): string {
  const normalized = String(provider || '').trim().toLowerCase();
  return PROVIDER_KEY_GUIDE_URLS[normalized] || 'https://docs.cherry-ai.com/pre-basic/settings/providers';
}

export default function SettingsView() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [payload, setPayload] = useState<GlobalSettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [sectionState, setSectionState] = useState<Record<string, SectionState>>({});
  const [agentTestResult, setAgentTestResult] = useState<{
    agent_id: string;
    ok: boolean;
    passed_count: number;
    failed_count: number;
    checks: Array<{ name: string; passed: boolean; stage: string; suggestion?: string; binary?: string; version?: string; path?: string; error?: string }>;
    checked_at: string;
  } | null>(null);
  const [agentTestScope, setAgentTestScope] = useState<'agent_settings' | 'pipeline_agent'>('agent_settings');
  const [agentTesting, setAgentTesting] = useState(false);
  const [agentInstalling, setAgentInstalling] = useState(false);
  const [installModal, setInstallModal] = useState<{
    open: boolean;
    scope: 'agent_settings' | 'pipeline_agent';
    steps: InstallStep[];
    done: boolean;
  }>({
    open: false,
    scope: 'agent_settings',
    done: false,
    steps: [
      { key: 'precheck', title: '检查 Node.js / Claude Code', status: 'pending', detail: '' },
      { key: 'install_node', title: '安装 Node.js（按需）', status: 'pending', detail: '' },
      { key: 'install_claude', title: '安装 Claude Code（按需）', status: 'pending', detail: '' },
      { key: 'postcheck', title: '安装后复查', status: 'pending', detail: '' },
    ],
  });
  const [templateEditor, setTemplateEditor] = useState<AgentTemplateEditorState>({
    open: false,
    section: '',
    kind: '',
    title: '',
    target: 'pipeline_skill',
    loading: false,
    saving: false,
    content: '',
    path: '',
    message: '',
  });

  const categories = useMemo(() => {
    const raw = payload?.schema?.categories ?? [];
    return raw
      .map((c) => ({ ...c, id: c.id === 'codex_global' ? 'agent_settings' : c.id }))
      .map((c) => ({ ...c, title: c.id === 'agent_settings' ? '知识问答 Agent' : c.title }))
      .filter((c) => c.id === 'pipeline' || c.id === 'translation' || c.id === 'agent_settings' || c.id === 'pipeline_agent' || c.id === 'embedding');
  }, [payload]);
  const otherCategories = useMemo(
    () => categories.filter((c) => !IMPORT_SECTION_IDS.has(c.id)),
    [categories],
  );

  useEffect(() => {
    api.settings.getAll()
      .then((data) => {
        const settings = { ...(data.settings ?? {}) } as Record<string, Record<string, unknown>>;
        if (settings.codex_global && !settings.agent_settings) {
          settings.agent_settings = settings.codex_global;
        }
        delete settings.llm_providers;
        delete settings.library_defaults;
        setPayload(data);
        setDrafts(settings);
      })
      .catch((err) => setLoadError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const updateField = (category: string, key: string, value: unknown) => {
    setDrafts((prev) => ({ ...prev, [category]: { ...asRecord(prev[category]), [key]: value } }));
  };

  const applyProviderPreset = async (category: string, providerId: string) => {
    const values = asRecord(drafts[category]);
    const presets = asPresets(values.provider_presets);
    const hit = presets.find((p) => p.id === providerId);
    if (!hit) return;
    const endpoint = `${hit.base_url.replace(/\/$/, '')}/v1/chat/completions`;
    const embEndpoint = `${hit.base_url.replace(/\/$/, '')}/embeddings`;
    // When switching providers, only send the provider identity + base_url.
    // Do NOT include model/api_key from the old provider's drafts — that would pollute
    // the new provider's saved data. The backend will return the new provider's saved
    // model/api_key (or empty defaults if never saved).
    let body: Record<string, unknown>;
    if (category === 'embedding') {
      body = { provider: providerId, endpoint_url: embEndpoint };
    } else if (category === 'agent_settings' || category === 'pipeline_agent') {
      body = { provider: providerId, base_url: hit.base_url };
    } else {
      body = { provider: providerId, base_url: hit.base_url, endpoint_url: endpoint };
    }
    try {
      const res = await api.settings.updateCategory(category, body);
      setDrafts((prev) => ({ ...prev, [category]: asRecord(res.config) }));
    } catch (_err) {
      // Fallback: update local fields only, user can click Save manually
      if (category === 'embedding') {
        setDrafts((prev) => ({ ...prev, embedding: { ...asRecord(prev.embedding), provider: providerId, endpoint_url: embEndpoint } }));
      } else if (category === 'agent_settings' || category === 'pipeline_agent') {
        setDrafts((prev) => ({ ...prev, [category]: { ...asRecord(prev[category]), provider: providerId, base_url: hit.base_url } }));
      } else {
        setDrafts((prev) => ({ ...prev, translation: { ...asRecord(prev.translation), provider: providerId, base_url: hit.base_url, endpoint_url: endpoint } }));
      }
    }
  };

  const saveCategory = async (category: string) => {
    const current = asRecord(drafts[category]);
    const {
      provider_presets: _drop1,
      recommendation: _drop2,
      reasoning_effort_options: _drop3,
      ...body
    } = current;
    setSectionState((prev) => ({ ...prev, [category]: { saving: true, message: '' } }));
    try {
      const res = await api.settings.updateCategory(category, body);
      setDrafts((prev) => ({ ...prev, [category]: asRecord(res.config) }));
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: '保存成功。' } }));
    } catch (err) {
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: `保存失败: ${(err as Error).message}` } }));
    }
  };

  const getAgentIdByScope = (scope: 'agent_settings' | 'pipeline_agent'): string => {
    if (scope === 'pipeline_agent') {
      return str(asRecord(drafts['pipeline_agent']).backend) || 'codex';
    }
    return str(asRecord(drafts['agent_settings']).current_agent) || 'codex';
  };

  const reuseAgentConfig = (source: 'agent_settings' | 'pipeline_agent', target: 'agent_settings' | 'pipeline_agent') => {
    const src = asRecord(drafts[source]);
    const patch = {
      provider: str(src.provider),
      model: str(src.model),
      api_key: str(src.api_key),
      base_url: str(src.base_url),
    };
    setDrafts((prev) => ({
      ...prev,
      [target]: { ...asRecord(prev[target]), ...patch },
    }));
    setSectionState((prev) => ({
      ...prev,
      [target]: { saving: false, message: '已复用对方 Agent 的当前配置，请点击保存生效。' },
    }));
  };

  const handleAgentInstall = async (scope: 'agent_settings' | 'pipeline_agent' = 'agent_settings') => {
    const agentId = getAgentIdByScope(scope);
    setAgentTestScope(scope);
    setAgentInstalling(true);
    setInstallModal({
      open: true,
      scope,
      done: false,
      steps: [
        { key: 'precheck', title: '检查 Node.js / Claude Code', status: 'pending', detail: '' },
        { key: 'install_node', title: '安装 Node.js（按需）', status: 'pending', detail: '' },
        { key: 'install_claude', title: '安装 Claude Code（按需）', status: 'pending', detail: '' },
        { key: 'postcheck', title: '安装后复查', status: 'pending', detail: '' },
      ],
    });
    const updateInstallStep = (key: InstallStep['key'], patch: Partial<InstallStep>) => {
      setInstallModal((prev) => ({
        ...prev,
        steps: prev.steps.map((s) => (s.key === key ? { ...s, ...patch } : s)),
      }));
    };
    try {
      const info = await api.agent.installInfo(agentId);
      if (info.not_available) {
        updateInstallStep('precheck', { status: 'failed', detail: `${info.display_name} 暂不支持安装` });
        setAgentTestResult({
          agent_id: agentId,
          ok: false,
          passed_count: 0,
          failed_count: 1,
          checks: [{ name: 'install_available', passed: false, stage: 'install', suggestion: info.display_name + ' 暂不支持安装' }],
          checked_at: new Date().toISOString(),
        });
        return;
      }
      const w = window as unknown as { desktopShell?: { runInTerminal?: (pkg: string, bin: string, name: string) => Promise<{ ok: boolean; error?: string }> } };
      const ds = w.desktopShell as unknown as {
        runInTerminal?: (pkg: string, bin: string, name: string) => Promise<{ ok: boolean; error?: string }>;
        agentPrecheck?: () => Promise<any>;
        agentInstallNode?: () => Promise<any>;
        agentInstallClaude?: () => Promise<any>;
        agentPostcheck?: () => Promise<any>;
      };
      if (agentId !== 'claude_code' || !ds?.agentPrecheck || !ds?.agentInstallNode || !ds?.agentInstallClaude || !ds?.agentPostcheck) {
        updateInstallStep('precheck', { status: 'running', detail: '正在打开终端执行安装脚本...' });
        const shell = ds?.runInTerminal;
        if (!shell) {
          updateInstallStep('precheck', { status: 'failed', detail: '桌面安装接口不可用' });
          return;
        }
        const pkg = info.command.replace(/^npm\s+install\s+-g\s+/, '').trim();
        const result = await shell(pkg, info.binary, info.display_name);
        if (!result.ok) {
          updateInstallStep('precheck', { status: 'failed', detail: result.error || '无法打开终端' });
          setAgentTestResult({
            agent_id: agentId,
            ok: false,
            passed_count: 0,
            failed_count: 1,
            checks: [{ name: 'install_launch', passed: false, stage: 'install', error: result.error || '无法打开终端' }],
            checked_at: new Date().toISOString(),
          });
        } else {
          updateInstallStep('precheck', { status: 'done', detail: '已启动外部终端，请按终端提示完成安装。' });
          updateInstallStep('install_node', { status: 'skipped', detail: '由终端脚本处理' });
          updateInstallStep('install_claude', { status: 'skipped', detail: '由终端脚本处理' });
          updateInstallStep('postcheck', { status: 'skipped', detail: '安装完成后可点“测试”复查' });
          setInstallModal((prev) => ({ ...prev, done: true }));
        }
        return;
      }

      updateInstallStep('precheck', { status: 'running', detail: '正在检查安装状态...' });
      setAgentTestResult({
        agent_id: agentId,
        ok: false,
        passed_count: 0,
        failed_count: 0,
        checks: [{ name: 'precheck', passed: true, stage: 'install', suggestion: '正在检查 Node.js / Claude Code...' }],
        checked_at: new Date().toISOString(),
      });

      const pre = await ds.agentPrecheck();
      const needsNode = !Boolean(pre?.node?.installed);
      const needsClaude = !Boolean(pre?.claude?.installed);
      updateInstallStep('precheck', { status: 'done', detail: `Node: ${pre?.node?.installed ? '已安装' : '缺失'}，Claude: ${pre?.claude?.installed ? '已安装' : '缺失'}` });
      if (!needsNode && !needsClaude) {
        updateInstallStep('install_node', { status: 'skipped', detail: '无需安装' });
        updateInstallStep('install_claude', { status: 'skipped', detail: '无需安装' });
        updateInstallStep('postcheck', { status: 'done', detail: '环境已就绪' });
        setInstallModal((prev) => ({ ...prev, done: true }));
        setAgentTestResult({
          agent_id: agentId,
          ok: true,
          passed_count: 1,
          failed_count: 0,
          checks: [{ name: 'already_installed', passed: true, stage: 'install', suggestion: '检测到 Node.js 和 Claude Code 已安装，可直接点击测试。' }],
          checked_at: new Date().toISOString(),
        });
        return;
      }

      if (needsNode) {
        updateInstallStep('install_node', { status: 'running', detail: '正在安装 Node.js...' });
        setAgentTestResult({
          agent_id: agentId,
          ok: false,
          passed_count: 0,
          failed_count: 0,
          checks: [{ name: 'install_node', passed: true, stage: 'install', suggestion: '缺少 Node.js，正在安装...' }],
          checked_at: new Date().toISOString(),
        });
        const n = await ds.agentInstallNode();
        if (!n?.ok || !n?.node?.installed) {
          updateInstallStep('install_node', { status: 'failed', detail: String(n?.error || 'node_install_failed') });
          updateInstallStep('install_claude', { status: 'skipped', detail: 'Node.js 未就绪，跳过' });
          updateInstallStep('postcheck', { status: 'failed', detail: '安装中断' });
          setInstallModal((prev) => ({ ...prev, done: true }));
          setAgentTestResult({
            agent_id: agentId,
            ok: false,
            passed_count: 0,
            failed_count: 1,
            checks: [{ name: 'install_node', passed: false, stage: 'install', error: String(n?.error || 'node_install_failed') }],
            checked_at: new Date().toISOString(),
          });
          return;
        }
        updateInstallStep('install_node', { status: 'done', detail: 'Node.js 安装完成' });
      } else {
        updateInstallStep('install_node', { status: 'skipped', detail: '已安装，跳过' });
      }

      if (needsClaude || !Boolean((await ds.agentPrecheck())?.claude?.installed)) {
        updateInstallStep('install_claude', { status: 'running', detail: '正在安装 Claude Code...' });
        setAgentTestResult({
          agent_id: agentId,
          ok: false,
          passed_count: 0,
          failed_count: 0,
          checks: [{ name: 'install_claude', passed: true, stage: 'install', suggestion: '正在安装 Claude Code...' }],
          checked_at: new Date().toISOString(),
        });
        const c = await ds.agentInstallClaude();
        if (!c?.ok || !c?.claude?.installed) {
          updateInstallStep('install_claude', { status: 'failed', detail: String(c?.error || 'claude_install_failed') });
          updateInstallStep('postcheck', { status: 'failed', detail: '安装中断' });
          setInstallModal((prev) => ({ ...prev, done: true }));
          setAgentTestResult({
            agent_id: agentId,
            ok: false,
            passed_count: 0,
            failed_count: 1,
            checks: [{ name: 'install_claude', passed: false, stage: 'install', error: String(c?.error || 'claude_install_failed') }],
            checked_at: new Date().toISOString(),
          });
          return;
        }
        updateInstallStep('install_claude', { status: 'done', detail: 'Claude Code 安装完成' });
      } else {
        updateInstallStep('install_claude', { status: 'skipped', detail: '已安装，跳过' });
      }

      updateInstallStep('postcheck', { status: 'running', detail: '正在复查环境...' });
      const post = await ds.agentPostcheck();
      const done = Boolean(post?.node?.installed) && Boolean(post?.claude?.installed);
      updateInstallStep('postcheck', { status: done ? 'done' : 'failed', detail: done ? '复查通过' : '复查失败，请重试' });
      setInstallModal((prev) => ({ ...prev, done: true }));
      setAgentTestResult({
        agent_id: agentId,
        ok: done,
        passed_count: done ? 1 : 0,
        failed_count: done ? 0 : 1,
        checks: [{
          name: 'install_done',
          passed: done,
          stage: 'install',
          suggestion: done ? '安装完成，可点击测试。' : '安装后校验失败，请重试或手动检查环境。',
          error: done ? undefined : 'postcheck_failed',
        }],
        checked_at: new Date().toISOString(),
      });
    } catch (err) {
      updateInstallStep('postcheck', { status: 'failed', detail: (err as Error).message || 'install_error' });
      setInstallModal((prev) => ({ ...prev, done: true }));
      setAgentTestResult({
        agent_id: agentId,
        ok: false,
        passed_count: 0,
        failed_count: 1,
        checks: [{ name: 'install_error', passed: false, stage: 'install', error: (err as Error).message }],
        checked_at: new Date().toISOString(),
      });
    } finally {
      setAgentInstalling(false);
    }
  };

  const handleAgentTest = async (scope: 'agent_settings' | 'pipeline_agent' = 'agent_settings') => {
    const agentId = getAgentIdByScope(scope);
    setAgentTestScope(scope);
    setAgentTesting(true);
    setAgentTestResult(null);
    try {
      const result = await api.agent.test(agentId);
      setAgentTestResult(result);
    } catch (err) {
      setAgentTestResult({
        agent_id: agentId,
        ok: false,
        passed_count: 0,
        failed_count: 1,
        checks: [{ name: 'test_error', passed: false, stage: 'system', error: (err as Error).message }],
        checked_at: new Date().toISOString(),
      });
    } finally {
      setAgentTesting(false);
    }
  };

  const loadTemplateEditor = async (
    section: 'pipeline_agent' | 'agent_settings',
    kind: 'skill' | 'md',
    target: AgentTemplateTarget,
    title: string,
  ) => {
    setTemplateEditor({
      open: true,
      section,
      kind,
      title,
      target,
      loading: true,
      saving: false,
      content: '',
      path: '',
      message: '',
    });
    try {
      const data = await api.settings.getAgentTemplate(target);
      setTemplateEditor((prev) => ({
        ...prev,
        loading: false,
        content: String(data.content ?? ''),
        path: String(data.path ?? ''),
      }));
    } catch (err) {
      setTemplateEditor((prev) => ({
        ...prev,
        loading: false,
        message: `加载失败: ${(err as Error).message}`,
      }));
    }
  };

  const switchMdTarget = async (target: AgentTemplateTarget) => {
    setTemplateEditor((prev) => ({ ...prev, target, loading: true, message: '' }));
    try {
      const data = await api.settings.getAgentTemplate(target);
      setTemplateEditor((prev) => ({
        ...prev,
        loading: false,
        content: String(data.content ?? ''),
        path: String(data.path ?? ''),
      }));
    } catch (err) {
      setTemplateEditor((prev) => ({
        ...prev,
        loading: false,
        message: `加载失败: ${(err as Error).message}`,
      }));
    }
  };

  const saveTemplateEditor = async () => {
    const { target, content } = templateEditor;
    setTemplateEditor((prev) => ({ ...prev, saving: true, message: '' }));
    try {
      const data = await api.settings.saveAgentTemplate(target, content);
      setTemplateEditor((prev) => ({
        ...prev,
        saving: false,
        content: String(data.content ?? ''),
        path: String(data.path ?? ''),
        message: '保存成功。',
      }));
    } catch (err) {
      setTemplateEditor((prev) => ({
        ...prev,
        saving: false,
        message: `保存失败: ${(err as Error).message}`,
      }));
    }
  };

  if (loading) return <div className="flex-1 overflow-auto p-8 bg-surface-container-low">正在加载设置...</div>;
  if (loadError) return <div className="flex-1 overflow-auto p-8 bg-surface-container-low text-error">设置加载失败: {loadError}</div>;

  return (
    <div className="flex-1 overflow-auto p-8 bg-surface-container-low">
      <div className="max-w-5xl mx-auto space-y-4">
        <h2 className="text-lg font-semibold text-on-surface">全局设置</h2>
        <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-5 space-y-4">
          <div className="text-base font-semibold text-on-surface">文献导入设置</div>
          <div className="rounded-xl border border-outline-variant p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-on-surface">PDF 转 Markdown 设置</div>
              <button
                disabled={(sectionState.pipeline ?? EMPTY_STATE).saving}
                onClick={() => saveCategory('pipeline')}
                className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50 text-xs"
              >
                {(sectionState.pipeline ?? EMPTY_STATE).saving ? '保存中...' : '保存'}
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <label>
                <div className="mb-1">MinerU API Key</div>
                <input className="w-full px-3 py-2 rounded border" type="password" value={str(asRecord(drafts.pipeline).mineru_api_key)} onChange={(e) => updateField('pipeline', 'mineru_api_key', e.target.value)} />
                <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href="https://mineru.net/apiManage/docs" target="_blank" rel="noreferrer">mineru.net/apiManage/docs</a></div>
              </label>
              <label>
                <div className="mb-1">提取模式</div>
                <input className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value="agent" readOnly />
              </label>
            </div>
            {(sectionState.pipeline ?? EMPTY_STATE).message ? <div className="text-sm text-on-surface-variant">{(sectionState.pipeline ?? EMPTY_STATE).message}</div> : null}
          </div>

          <div className="rounded-xl border border-outline-variant p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-on-surface">文献管理 Agent</div>
                <div className="text-xs text-on-surface-variant">复用配置仅同步到当前页面草稿，需点击保存后生效。</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadTemplateEditor('pipeline_agent', 'skill', 'pipeline_skill', '编辑文献管理 Agent Skill 模板')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                >
                  编辑 Skill
                </button>
                <button
                  onClick={() => loadTemplateEditor('pipeline_agent', 'md', 'claude_md', '编辑文献管理 Agent MD')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                >
                  编辑 MD
                </button>
                <button
                  onClick={() => reuseAgentConfig('agent_settings', 'pipeline_agent')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                  title="复用「知识问答 Agent」当前选择的 provider/model/api_key/base_url"
                >
                  复用知识问答配置
                </button>
                <button
                  disabled={agentInstalling}
                  onClick={() => handleAgentInstall('pipeline_agent')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                  title="打开终端安装当前选中的 Agent CLI"
                >
                  {agentInstalling ? '安装中...' : '安装'}
                </button>
                <button
                  disabled={agentTesting}
                  onClick={() => handleAgentTest('pipeline_agent')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                  title="测试当前 Agent 是否正确配置"
                >
                  {agentTesting ? '测试中...' : '测试'}
                </button>
                <button
                  disabled={(sectionState.pipeline_agent ?? EMPTY_STATE).saving}
                  onClick={() => saveCategory('pipeline_agent')}
                  className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50 text-xs"
                >
                  {(sectionState.pipeline_agent ?? EMPTY_STATE).saving ? '保存中...' : '保存'}
                </button>
              </div>
            </div>
            {(() => {
              const values = asRecord(drafts.pipeline_agent);
              const presets = (((values.provider_presets as ProviderPreset[]) || []).length > 0
                ? ((values.provider_presets as ProviderPreset[]) || [])
                : DEFAULT_PROVIDER_PRESETS);
              const backend = str(values.backend) || 'codex';
              const effortOptions = getEffortOptions(values, backend);
              const currentEffort = str(values.reasoning_effort).toLowerCase();
              const effectiveEffort = effortOptions.includes(currentEffort) ? currentEffort : (effortOptions[0] ?? '');
              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label>
                    <div className="mb-1">Agent 后端</div>
                    <select className="w-full px-3 py-2 rounded border" value={str(values.backend)} onChange={(e) => {
                      const nextBackend = e.target.value;
                      updateField('pipeline_agent', 'backend', nextBackend);
                      const nextOptions = getEffortOptions(values, nextBackend);
                      if (nextOptions.length > 0) updateField('pipeline_agent', 'reasoning_effort', nextOptions[0]);
                    }}>
                      <option value="codex">Codex</option>
                      <option value="claude_code">Claude Code</option>
                      <option value="gemini_cli">Gemini CLI</option>
                    </select>
                  </label>
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('pipeline_agent', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField('pipeline_agent', 'model', e.target.value)} /></label>
                  <label>
                    <div className="mb-1">思考深度</div>
                    <select className="w-full px-3 py-2 rounded border" value={effectiveEffort} onChange={(e) => updateField('pipeline_agent', 'reasoning_effort', e.target.value)} disabled={effortOptions.length === 0}>
                      {effortOptions.length === 0 ? <option value="">不支持</option> : null}
                      {effortOptions.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  </label>
                  <label>
                    <div className="mb-1">API Key</div>
                    <input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField('pipeline_agent', 'api_key', e.target.value)} />
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                  </label>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField('pipeline_agent', 'base_url', e.target.value)} /></label>
                </div>
              );
            })()}
            <div className="text-on-surface-variant text-sm">用于文献导入提取任务的 Agent 配置。</div>
            {agentTestScope === 'pipeline_agent' && agentTestResult && (
              <div className={`rounded-lg border p-3 text-sm space-y-2 ${agentTestResult.ok ? 'border-green-300 bg-green-50' : 'border-amber-300 bg-amber-50'}`}>
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${agentTestResult.ok ? 'text-green-700' : 'text-amber-700'}`}>
                    {agentTestResult.ok ? '验证通过' : '发现问题'} ({agentTestResult.passed_count}/{agentTestResult.passed_count + agentTestResult.failed_count})
                  </span>
                  <button
                    onClick={() => setAgentTestResult(null)}
                    className="text-xs text-on-surface-variant hover:text-on-surface"
                  >
                    关闭
                  </button>
                </div>
                {agentTestResult.checks.map((check, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="mt-0.5">{check.passed ? '✅' : '❌'}</span>
                    <div>
                      <span className="font-medium">{check.name}</span>
                      {check.version ? <span className="ml-2 text-on-surface-variant">v{check.version}</span> : null}
                      {check.binary ? <div className="text-on-surface-variant truncate max-w-md">{check.binary}</div> : null}
                      {check.path ? <div className="text-on-surface-variant truncate max-w-md">{check.path}</div> : null}
                      {!check.passed && (check.suggestion || check.error) ? (
                        <div className="text-amber-700 mt-0.5">{check.suggestion || check.error}</div>
                      ) : null}
                    </div>
                  </div>
                ))}
                <div className="text-xs text-on-surface-variant">检查时间: {agentTestResult.checked_at}</div>
              </div>
            )}
            {(sectionState.pipeline_agent ?? EMPTY_STATE).message ? <div className="text-sm text-on-surface-variant">{(sectionState.pipeline_agent ?? EMPTY_STATE).message}</div> : null}
          </div>

          <div className="rounded-xl border border-outline-variant p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-on-surface">语义 Embedding 设置</div>
              <button
                disabled={(sectionState.embedding ?? EMPTY_STATE).saving}
                onClick={() => saveCategory('embedding')}
                className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50 text-xs"
              >
                {(sectionState.embedding ?? EMPTY_STATE).saving ? '保存中...' : '保存'}
              </button>
            </div>
            {(() => {
              const values = asRecord(drafts.embedding);
              const presets = (((values.provider_presets as ProviderPreset[]) || []).length > 0
                ? ((values.provider_presets as ProviderPreset[]) || [])
                : DEFAULT_PROVIDER_PRESETS);
              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('embedding', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField('embedding', 'model', e.target.value)} /></label>
                  <label>
                    <div className="mb-1">API Key</div>
                    <input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField('embedding', 'api_key', e.target.value)} />
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                  </label>
                  <label className="md:col-span-2"><div className="mb-1">Endpoint URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.endpoint_url)} onChange={(e) => updateField('embedding', 'endpoint_url', e.target.value)} /></label>
                </div>
              );
            })()}
            {(sectionState.embedding ?? EMPTY_STATE).message ? <div className="text-sm text-on-surface-variant">{(sectionState.embedding ?? EMPTY_STATE).message}</div> : null}
          </div>
        </div>

        {otherCategories.map((category) => {
          const id = category.id;
          const state = sectionState[id] ?? EMPTY_STATE;
          const values = asRecord(drafts[id]);
          const presets = (((values.provider_presets as ProviderPreset[]) || []).length > 0
            ? ((values.provider_presets as ProviderPreset[]) || [])
            : DEFAULT_PROVIDER_PRESETS);
          return (
            <div key={id} className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-5 space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-base font-semibold text-on-surface">{category.title}</div>
                  {category.restart_required ? <div className="text-xs text-on-surface-variant">该配置保存后需要重启生效。</div> : null}
                  {id === 'agent_settings' ? <div className="text-xs text-on-surface-variant">复用配置仅同步到当前页面草稿，需点击保存后生效。</div> : null}
                </div>
                <div className="flex items-center gap-2">
                  {id === 'agent_settings' && (
                    <>
                      <button
                        onClick={() => loadTemplateEditor('agent_settings', 'skill', 'qa_skill', '编辑知识问答 Agent Skill 模板')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                      >
                        编辑 Skill
                      </button>
                      <button
                        onClick={() => loadTemplateEditor('agent_settings', 'md', 'claude_md', '编辑知识问答 Agent MD')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                      >
                        编辑 MD
                      </button>
                      <button
                        onClick={() => reuseAgentConfig('pipeline_agent', 'agent_settings')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest border border-outline-variant"
                        title="复用「文献管理 Agent」当前选择的 provider/model/api_key/base_url"
                      >
                        复用文献管理配置
                      </button>
                      <button
                        disabled={agentInstalling}
                        onClick={() => handleAgentInstall('agent_settings')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                        title="打开终端安装当前选中的 Agent CLI"
                      >
                        {agentInstalling ? '安装中...' : '安装'}
                      </button>
                      <button
                        disabled={agentTesting}
                        onClick={() => handleAgentTest('agent_settings')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                        title="测试当前 Agent 是否正确配置"
                      >
                        {agentTesting ? '测试中...' : '测试'}
                      </button>
                    </>
                  )}
                  <button disabled={state.saving} onClick={() => saveCategory(id)} className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50">
                    {state.saving ? '保存中...' : '保存'}
                  </button>
                </div>
              </div>

              {id === 'pipeline' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">MinerU API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.mineru_api_key)} onChange={(e) => updateField(id, 'mineru_api_key', e.target.value)} /></label>
                  <label><div className="mb-1">提取模式</div><input className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value="agent" readOnly /></label>
                  <div className="md:col-span-2 text-on-surface-variant">文献导入仅支持 Agent 模式，使用下方「Pipeline Agent」分类中配置的 Agent 后端进行三步提取（提取→消歧→笔记）。</div>
                </div>
              )}

              {id === 'translation' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">翻译提供商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('translation', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">翻译模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label>
                    <div className="mb-1">API Key</div>
                    <input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} />
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                  </label>
                  <label><div className="mb-1">目标语言</div><input className="w-full px-3 py-2 rounded border" value={str(values.target_lang)} onChange={(e) => updateField(id, 'target_lang', e.target.value)} /></label>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField(id, 'base_url', e.target.value)} /></label>
                  <label><div className="mb-1">Endpoint URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.endpoint_url)} onChange={(e) => updateField(id, 'endpoint_url', e.target.value)} /></label>
                  <div className="md:col-span-2 text-on-surface-variant">{str(values.recommendation || '建议优先使用 deepseek-v4-flash。')}</div>
                </div>
              )}

              {id === 'agent_settings' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label>
                    <div className="mb-1">当前应用 Agent</div>
                    <select className="w-full px-3 py-2 rounded border" value={str(values.current_agent || 'codex')} onChange={(e) => updateField(id, 'current_agent', e.target.value)}>
                      {(values.available_agents as string[] || ['codex', 'claude_code', 'gemini_cli', 'hermes', 'opencode', 'openclaw']).map((a) => (
                        <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </label>
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('agent_settings', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label>
                    <div className="mb-1">API Key</div>
                    <input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} />
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                  </label>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField(id, 'base_url', e.target.value)} /></label>
                </div>
              )}

              {id === 'agent_settings' && agentTestScope === 'agent_settings' && agentTestResult && (
                <div className={`rounded-lg border p-3 text-sm space-y-2 ${agentTestResult.ok ? 'border-green-300 bg-green-50' : 'border-amber-300 bg-amber-50'}`}>
                  <div className="flex items-center justify-between">
                    <span className={`font-semibold ${agentTestResult.ok ? 'text-green-700' : 'text-amber-700'}`}>
                      {agentTestResult.ok ? '验证通过' : '发现问题'} ({agentTestResult.passed_count}/{agentTestResult.passed_count + agentTestResult.failed_count})
                    </span>
                    <button
                      onClick={() => setAgentTestResult(null)}
                      className="text-xs text-on-surface-variant hover:text-on-surface"
                    >
                      关闭
                    </button>
                  </div>
                  {agentTestResult.checks.map((check, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <span className="mt-0.5">{check.passed ? '✅' : '❌'}</span>
                      <div>
                        <span className="font-medium">{check.name}</span>
                        {check.version ? <span className="ml-2 text-on-surface-variant">v{check.version}</span> : null}
                        {check.binary ? <div className="text-on-surface-variant truncate max-w-md">{check.binary}</div> : null}
                        {check.path ? <div className="text-on-surface-variant truncate max-w-md">{check.path}</div> : null}
                        {!check.passed && (check.suggestion || check.error) ? (
                          <div className="text-amber-700 mt-0.5">{check.suggestion || check.error}</div>
                        ) : null}
                      </div>
                    </div>
                  ))}
                  <div className="text-xs text-on-surface-variant">检查时间: {agentTestResult.checked_at}</div>
                </div>
              )}
              {state.message ? <div className="text-sm text-on-surface-variant">{state.message}</div> : null}
            </div>
          );
        })}
      </div>
      {templateEditor.open && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-5xl max-h-[85vh] bg-surface border border-outline-variant rounded-2xl shadow-xl flex flex-col">
            <div className="px-5 py-3 border-b border-outline-variant flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-on-surface truncate">{templateEditor.title}</div>
                <div className="text-xs text-on-surface-variant truncate">{templateEditor.path || '未加载'}</div>
              </div>
              <button
                onClick={() => setTemplateEditor((prev) => ({ ...prev, open: false }))}
                className="px-3 py-1.5 text-xs rounded border border-outline-variant bg-surface-container-high text-on-surface"
              >
                关闭
              </button>
            </div>
            {templateEditor.kind === 'md' && (
              <div className="px-5 pt-3">
                <select
                  className="px-3 py-2 rounded border text-sm"
                  value={templateEditor.target}
                  onChange={(e) => switchMdTarget(e.target.value as AgentTemplateTarget)}
                >
                  <option value="claude_md">template_agent.md</option>
                  <option value="agent_md">template_agent.md（兼容别名）</option>
                </select>
              </div>
            )}
            <div className="px-5 py-3 flex-1 min-h-0">
              <textarea
                className="w-full h-full min-h-[420px] p-3 rounded border bg-surface-container-low font-mono text-xs outline-none"
                value={templateEditor.content}
                onChange={(e) => setTemplateEditor((prev) => ({ ...prev, content: e.target.value }))}
                disabled={templateEditor.loading}
                spellCheck={false}
              />
            </div>
            <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-between gap-3">
              <div className="text-xs text-on-surface-variant">
                {templateEditor.loading ? '加载中...' : templateEditor.message || '仅点击“保存”后才会写入模板文件。'}
              </div>
              <button
                onClick={saveTemplateEditor}
                disabled={templateEditor.loading || templateEditor.saving}
                className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50 text-xs"
              >
                {templateEditor.saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
      {installModal.open && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-surface border border-outline-variant rounded-2xl shadow-xl">
            <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-on-surface">Agent 安装向导</div>
                <div className="text-xs text-on-surface-variant">按检查项逐步安装（待办模式）</div>
              </div>
              <button
                onClick={() => installModal.done && setInstallModal((prev) => ({ ...prev, open: false }))}
                disabled={!installModal.done}
                className="px-3 py-1.5 text-xs rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50"
              >
                关闭
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              {installModal.steps.map((s) => {
                const marker = s.status === 'done' ? '✅' : s.status === 'failed' ? '❌' : s.status === 'running' ? '⏳' : s.status === 'skipped' ? '⏭️' : '•';
                const color = s.status === 'done'
                  ? 'text-green-700'
                  : s.status === 'failed'
                    ? 'text-red-700'
                    : s.status === 'running'
                      ? 'text-blue-700'
                      : 'text-on-surface-variant';
                return (
                  <div key={s.key} className="rounded-lg border border-outline-variant bg-surface-container-low p-3">
                    <div className={`font-medium text-sm ${color}`}>{marker} {s.title}</div>
                    <div className="text-xs text-on-surface-variant mt-1">{s.detail || '等待执行...'}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
