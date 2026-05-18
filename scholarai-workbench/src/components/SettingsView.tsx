import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { GlobalSettingsPayload } from '../types';
import {
  buildAgentInstallRows,
  type AgentInstallBusyAction,
  type AgentInstallDetection,
  type AgentInstallInfo,
  type AgentInstallTestResult,
} from './settingsAgentInstall';

type SectionState = { saving: boolean; message: string };
type KeyTestState = { testing: boolean; message: string };
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
type AgentTestResult = {
  agent_id: string;
  ok: boolean;
  passed_count: number;
  failed_count: number;
  checks: Array<{ name: string; passed: boolean; stage: string; suggestion?: string; binary?: string; version?: string; path?: string; error?: string }>;
  checked_at: string;
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
const EMPTY_TEST_STATE: KeyTestState = { testing: false, message: '' };
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
const EMBEDDING_PROVIDER_PRESETS = DEFAULT_PROVIDER_PRESETS.filter((p) => p.id === 'zhipu');
const ONLY_AGENT_BACKEND = 'claude_code';

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
function keyTestMessage(result: Record<string, unknown>): string {
  if (result.ok) {
    const latency = Number(result.latency_ms ?? 0);
    return latency > 0 ? `测试通过（${latency} ms）。` : '测试通过。';
  }
  const detail = str(result.detail || result.error || 'unknown_error');
  return `测试失败: ${detail}`;
}

export default function SettingsView() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [payload, setPayload] = useState<GlobalSettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [sectionState, setSectionState] = useState<Record<string, SectionState>>({});
  const [keyTestState, setKeyTestState] = useState<Record<string, KeyTestState>>({});
  const [installModal, setInstallModal] = useState<{
    open: boolean;
    scope: 'agent_settings' | 'pipeline_agent';
    agentId: string;
    info: AgentInstallInfo | null;
    detection: AgentInstallDetection | null;
    testResult: AgentTestResult | null;
    busyAction: AgentInstallBusyAction;
    message: string;
  }>({
    open: false,
    scope: 'agent_settings',
    agentId: 'codex',
    info: null,
    detection: null,
    testResult: null,
    busyAction: '',
    message: '',
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
      return ONLY_AGENT_BACKEND;
    }
    return ONLY_AGENT_BACKEND;
  };

  const apiKeyPayload = (category: string): Record<string, unknown> => {
    const current = asRecord(drafts[category]);
    const {
      provider_presets: _drop1,
      recommendation: _drop2,
      reasoning_effort_options: _drop3,
      available_agents: _drop4,
      ...body
    } = current;
    if (category === 'embedding') return { ...body, provider: 'zhipu' };
    if (category === 'pipeline_agent') return { ...body, backend: ONLY_AGENT_BACKEND };
    if (category === 'agent_settings') return { ...body, current_agent: ONLY_AGENT_BACKEND };
    return body;
  };

  const testApiKey = async (category: string) => {
    setKeyTestState((prev) => ({ ...prev, [category]: { testing: true, message: '' } }));
    try {
      const result = await api.settings.testApiKey(category, apiKeyPayload(category));
      setKeyTestState((prev) => ({ ...prev, [category]: { testing: false, message: keyTestMessage(result) } }));
    } catch (err) {
      setKeyTestState((prev) => ({ ...prev, [category]: { testing: false, message: `测试失败: ${(err as Error).message}` } }));
    }
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

  const normalizeInstallInfo = (raw: Awaited<ReturnType<typeof api.agent.installInfo>>): AgentInstallInfo => ({
    displayName: raw.display_name || raw.agent_id,
    binary: raw.binary || '',
    installCommand: raw.command || '',
    notAvailable: Boolean(raw.not_available),
  });

  const refreshAgentInstallStatus = async (agentId: string, keepTestResult = true) => {
    setInstallModal((prev) => ({ ...prev, busyAction: 'detect', message: '正在检测 Node.js 和 Agent CLI...' }));
    try {
      const info = await api.agent.installInfo(agentId);
      const normalized = normalizeInstallInfo(info);
      const ds = window.desktopShell;
      if (!ds?.agentPrecheck) {
        setInstallModal((prev) => ({
          ...prev,
          info: normalized,
          busyAction: '',
          message: '桌面检测接口不可用，请在 Electron 桌面端使用。',
        }));
        return;
      }
      const pre = await ds.agentPrecheck(normalized.binary);
      setInstallModal((prev) => ({
        ...prev,
        info: normalized,
        detection: {
          node: pre?.node ?? { installed: false },
          npm: pre?.npm ?? { installed: false },
          agent: pre?.agent ?? { installed: false },
        },
        testResult: keepTestResult ? prev.testResult : null,
        busyAction: '',
        message: '检测完成。',
      }));
    } catch (err) {
      setInstallModal((prev) => ({ ...prev, busyAction: '', message: `检测失败: ${(err as Error).message}` }));
    }
  };

  const handleAgentInstall = async (scope: 'agent_settings' | 'pipeline_agent' = 'agent_settings') => {
    const agentId = getAgentIdByScope(scope);
    setInstallModal({
      open: true,
      scope,
      agentId,
      info: null,
      detection: null,
      testResult: null,
      busyAction: 'detect',
      message: '正在打开安装检测面板...',
    });
    await refreshAgentInstallStatus(agentId, false);
  };

  const runInstallCommand = async (action: 'install_node' | 'install_agent') => {
    const ds = window.desktopShell;
    const info = installModal.info;
    if (!ds?.runTerminalCommand || !info) {
      setInstallModal((prev) => ({ ...prev, message: '桌面终端接口不可用。' }));
      return;
    }
    const command = action === 'install_node'
      ? 'winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements'
      : info.installCommand;
    const label = action === 'install_node' ? 'Node.js LTS' : info.displayName;
    setInstallModal((prev) => ({ ...prev, busyAction: action, message: `正在打开终端执行 ${label} 安装命令...` }));
    const result = await ds.runTerminalCommand(label, command);
    setInstallModal((prev) => ({
      ...prev,
      busyAction: '',
      message: result.ok ? '已打开终端。安装完成后点击“刷新”重新检测。' : `无法打开终端: ${result.error || 'unknown_error'}`,
    }));
  };

  const handleAgentTest = async () => {
    const agentId = installModal.agentId;
    setInstallModal((prev) => ({ ...prev, busyAction: 'test', message: '正在测试当前 Agent...' }));
    try {
      const result = await api.agent.test(agentId);
      setInstallModal((prev) => ({ ...prev, testResult: result, busyAction: '', message: result.ok ? '测试通过。' : '测试发现问题。' }));
    } catch (err) {
      const result: AgentTestResult = {
        agent_id: agentId,
        ok: false,
        passed_count: 0,
        failed_count: 1,
        checks: [{ name: 'test_error', passed: false, stage: 'system', error: (err as Error).message }],
        checked_at: new Date().toISOString(),
      };
      setInstallModal((prev) => ({ ...prev, testResult: result, busyAction: '', message: '测试失败。' }));
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
              <div>
                <div className="mb-1">MinerU API Key</div>
                <div className="flex gap-2">
                  <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(asRecord(drafts.pipeline).mineru_api_key)} onChange={(e) => updateField('pipeline', 'mineru_api_key', e.target.value)} />
                  <button
                    type="button"
                    disabled={(keyTestState.pipeline ?? EMPTY_TEST_STATE).testing}
                    onClick={() => testApiKey('pipeline')}
                    className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                  >
                    {(keyTestState.pipeline ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                  </button>
                </div>
                <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href="https://mineru.net/apiManage/docs" target="_blank" rel="noreferrer">mineru.net/apiManage/docs</a></div>
                {(keyTestState.pipeline ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState.pipeline ?? EMPTY_TEST_STATE).message}</div> : null}
              </div>
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
                  onClick={() => handleAgentInstall('pipeline_agent')}
                  className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                  title="检测、安装并测试当前选中的 Agent CLI"
                >
                  安装/检测
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
              const backend = ONLY_AGENT_BACKEND;
              const effortOptions = getEffortOptions(values, backend);
              const currentEffort = str(values.reasoning_effort).toLowerCase();
              const effectiveEffort = effortOptions.includes(currentEffort) ? currentEffort : (effortOptions[0] ?? '');
              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label>
                    <div className="mb-1">Agent 后端</div>
                    <select className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value={ONLY_AGENT_BACKEND} disabled onChange={() => {}}>
                      <option value="claude_code">Claude Code</option>
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
                  <div>
                    <div className="mb-1">API Key</div>
                    <div className="flex gap-2">
                      <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField('pipeline_agent', 'api_key', e.target.value)} />
                      <button
                        type="button"
                        disabled={(keyTestState.pipeline_agent ?? EMPTY_TEST_STATE).testing}
                        onClick={() => testApiKey('pipeline_agent')}
                        className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                      >
                        {(keyTestState.pipeline_agent ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                    {(keyTestState.pipeline_agent ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState.pipeline_agent ?? EMPTY_TEST_STATE).message}</div> : null}
                  </div>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField('pipeline_agent', 'base_url', e.target.value)} /></label>
                </div>
              );
            })()}
            <div className="text-on-surface-variant text-sm">用于文献导入提取任务的 Agent 配置。</div>
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
              const presets = EMBEDDING_PROVIDER_PRESETS;
              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value="zhipu" disabled onChange={() => {}}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField('embedding', 'model', e.target.value)} /></label>
                  <div>
                    <div className="mb-1">API Key</div>
                    <div className="flex gap-2">
                      <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField('embedding', 'api_key', e.target.value)} />
                      <button
                        type="button"
                        disabled={(keyTestState.embedding ?? EMPTY_TEST_STATE).testing}
                        onClick={() => testApiKey('embedding')}
                        className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                      >
                        {(keyTestState.embedding ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                    {(keyTestState.embedding ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState.embedding ?? EMPTY_TEST_STATE).message}</div> : null}
                  </div>
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
                        onClick={() => handleAgentInstall('agent_settings')}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                        title="检测、安装并测试当前选中的 Agent CLI"
                      >
                        安装/检测
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
                  <div>
                    <div className="mb-1">MinerU API Key</div>
                    <div className="flex gap-2">
                      <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(values.mineru_api_key)} onChange={(e) => updateField(id, 'mineru_api_key', e.target.value)} />
                      <button
                        type="button"
                        disabled={(keyTestState[id] ?? EMPTY_TEST_STATE).testing}
                        onClick={() => testApiKey(id)}
                        className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                      >
                        {(keyTestState[id] ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                      </button>
                    </div>
                    {(keyTestState[id] ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState[id] ?? EMPTY_TEST_STATE).message}</div> : null}
                  </div>
                  <label><div className="mb-1">提取模式</div><input className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value="agent" readOnly /></label>
                  <div className="md:col-span-2 text-on-surface-variant">文献导入仅支持 Agent 模式，使用下方「Pipeline Agent」分类中配置的 Agent 后端进行三步提取（提取→消歧→笔记）。</div>
                </div>
              )}

              {id === 'translation' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">翻译提供商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('translation', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">翻译模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <div>
                    <div className="mb-1">API Key</div>
                    <div className="flex gap-2">
                      <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} />
                      <button
                        type="button"
                        disabled={(keyTestState[id] ?? EMPTY_TEST_STATE).testing}
                        onClick={() => testApiKey(id)}
                        className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                      >
                        {(keyTestState[id] ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                    {(keyTestState[id] ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState[id] ?? EMPTY_TEST_STATE).message}</div> : null}
                  </div>
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
                    <select className="w-full px-3 py-2 rounded border bg-surface-container-low text-on-surface-variant" value={ONLY_AGENT_BACKEND} disabled onChange={() => {}}>
                      {['claude_code'].map((a) => (
                        <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </label>
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('agent_settings', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <div>
                    <div className="mb-1">API Key</div>
                    <div className="flex gap-2">
                      <input className="min-w-0 flex-1 px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} />
                      <button
                        type="button"
                        disabled={(keyTestState[id] ?? EMPTY_TEST_STATE).testing}
                        onClick={() => testApiKey(id)}
                        className="px-3 py-2 rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50 text-xs whitespace-nowrap"
                      >
                        {(keyTestState[id] ?? EMPTY_TEST_STATE).testing ? '测试中...' : '测试 Key'}
                      </button>
                    </div>
                    <div className="mt-1 text-xs text-on-surface-variant">获取地址：<a className="underline" href={providerKeyGuideUrl(str(values.provider))} target="_blank" rel="noreferrer">{providerKeyGuideUrl(str(values.provider))}</a></div>
                    {(keyTestState[id] ?? EMPTY_TEST_STATE).message ? <div className="mt-1 text-xs text-on-surface-variant">{(keyTestState[id] ?? EMPTY_TEST_STATE).message}</div> : null}
                  </div>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField(id, 'base_url', e.target.value)} /></label>
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
                <div className="text-sm font-semibold text-on-surface">Agent 安装与测试</div>
                <div className="text-xs text-on-surface-variant">
                  {installModal.info?.displayName || installModal.agentId} · 自动检测 Node.js 与当前 Agent CLI
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => refreshAgentInstallStatus(installModal.agentId)}
                  disabled={installModal.busyAction !== ''}
                  className="px-3 py-1.5 text-xs rounded border border-outline-variant bg-surface-container-high text-on-surface disabled:opacity-50"
                >
                  刷新
                </button>
                <button
                  onClick={() => setInstallModal((prev) => ({ ...prev, open: false }))}
                  className="px-3 py-1.5 text-xs rounded border border-outline-variant bg-surface-container-high text-on-surface"
                >
                  关闭
                </button>
              </div>
            </div>
            {(() => {
              const rows = buildAgentInstallRows({
                agent: installModal.info ?? { displayName: installModal.agentId, binary: '', installCommand: '' },
                detection: installModal.detection,
                testResult: installModal.testResult as AgentInstallTestResult,
                busyAction: installModal.busyAction,
              });
              const renderStatus = (status: string) => {
                if (status === 'installed') return <span className="text-green-700 font-bold">✓</span>;
                if (status === 'missing' || status === 'failed' || status === 'unsupported') return <span className="text-red-700 font-bold">×</span>;
                if (status === 'running') return <span className="text-blue-700 font-bold">...</span>;
                return <span className="text-on-surface-variant font-bold">?</span>;
              };
              return (
                <div className="px-5 py-4 space-y-3">
                  <div className="rounded-lg border border-outline-variant bg-surface-container-low p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-sm text-on-surface flex items-center gap-2">{renderStatus(rows.node.status)} Node.js / npm</div>
                      <div className="text-xs text-on-surface-variant mt-1 truncate">{rows.node.detail}</div>
                      <div className="text-[11px] text-on-surface-variant mt-1 font-mono truncate">{rows.node.installCommand}</div>
                    </div>
                    <button
                      onClick={() => runInstallCommand('install_node')}
                      disabled={!rows.node.canInstall || installModal.busyAction !== ''}
                      className="px-3 py-1.5 text-xs rounded bg-secondary text-on-secondary disabled:opacity-50 whitespace-nowrap"
                    >
                      安装
                    </button>
                  </div>
                  <div className="rounded-lg border border-outline-variant bg-surface-container-low p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-sm text-on-surface flex items-center gap-2">
                        {renderStatus(rows.agent.status)} {installModal.info?.displayName || 'Agent CLI'}
                      </div>
                      <div className="text-xs text-on-surface-variant mt-1 truncate">{rows.agent.detail}</div>
                      <div className="text-[11px] text-on-surface-variant mt-1 font-mono truncate">{rows.agent.installCommand || rows.agent.disabledReason}</div>
                    </div>
                    <button
                      onClick={() => runInstallCommand('install_agent')}
                      disabled={!rows.agent.canInstall || installModal.busyAction !== ''}
                      title={rows.agent.disabledReason}
                      className="px-3 py-1.5 text-xs rounded bg-secondary text-on-secondary disabled:opacity-50 whitespace-nowrap"
                    >
                      安装
                    </button>
                  </div>
                  <div className="rounded-lg border border-outline-variant bg-surface-container-low p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-sm text-on-surface flex items-center gap-2">{renderStatus(rows.test.status)} Agent 测试</div>
                      <div className="text-xs text-on-surface-variant mt-1">{rows.test.detail}</div>
                      {rows.test.checks.length > 0 ? (
                        <div className="mt-2 space-y-1.5">
                          {rows.test.checks.map((check) => (
                            <div key={check.name} className="rounded-md border border-outline-variant/70 bg-surface-container-lowest px-2 py-1.5">
                              <div className="flex items-center gap-2 text-xs text-on-surface">
                                {renderStatus(check.status)}
                                <span className="font-medium">{check.label}</span>
                                <span className="text-[10px] text-outline">({check.stage})</span>
                              </div>
                              <div className="text-[11px] text-on-surface-variant mt-1 break-words">{check.detail}</div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {installModal.testResult?.checked_at ? <div className="text-[11px] text-on-surface-variant mt-1">检查时间: {installModal.testResult.checked_at}</div> : null}
                    </div>
                    <button
                      onClick={handleAgentTest}
                      disabled={!rows.test.canRun || installModal.busyAction !== ''}
                      className="px-3 py-1.5 text-xs rounded bg-secondary text-on-secondary disabled:opacity-50 whitespace-nowrap"
                    >
                      测试
                    </button>
                  </div>
                  {installModal.message ? <div className="text-xs text-on-surface-variant">{installModal.message}</div> : null}
                </div>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
