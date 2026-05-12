import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { GlobalSettingsPayload } from '../types';

type SectionState = { saving: boolean; message: string };
type ProviderPreset = { id: string; name: string; base_url: string };

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
  const [agentTesting, setAgentTesting] = useState(false);
  const [agentInstalling, setAgentInstalling] = useState(false);

  const categories = useMemo(() => {
    const raw = payload?.schema?.categories ?? [];
    return raw
      .map((c) => ({ ...c, id: c.id === 'codex_global' ? 'agent_settings' : c.id }))
      .filter((c) => c.id === 'pipeline' || c.id === 'translation' || c.id === 'agent_settings' || c.id === 'pipeline_agent' || c.id === 'embedding');
  }, [payload]);

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
    if (category === 'pipeline') {
      body = { fast_provider: providerId, fast_base_url: hit.base_url, fast_endpoint_url: endpoint };
    } else if (category === 'embedding') {
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
      if (category === 'pipeline') {
        setDrafts((prev) => ({ ...prev, pipeline: { ...asRecord(prev.pipeline), fast_provider: providerId, fast_base_url: hit.base_url, fast_endpoint_url: endpoint } }));
      } else if (category === 'embedding') {
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

  const handleAgentInstall = async () => {
    const agentId = str(asRecord(drafts['agent_settings']).current_agent) || 'codex';
    setAgentInstalling(true);
    try {
      const info = await api.agent.installInfo(agentId);
      if (info.not_available) {
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
      const shell = w.desktopShell?.runInTerminal;
      if (!shell) return;
      // Extract package name from "npm install -g <pkg>"
      const pkg = info.command.replace(/^npm\s+install\s+-g\s+/, '').trim();
      const result = await shell(pkg, info.binary, info.display_name);
      if (!result.ok) {
        setAgentTestResult({
          agent_id: agentId,
          ok: false,
          passed_count: 0,
          failed_count: 1,
          checks: [{ name: 'install_launch', passed: false, stage: 'install', error: result.error || '无法打开终端' }],
          checked_at: new Date().toISOString(),
        });
      }
    } catch (err) {
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

  const handleAgentTest = async () => {
    const agentId = str(asRecord(drafts['agent_settings']).current_agent) || 'codex';
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

  if (loading) return <div className="flex-1 overflow-auto p-8 bg-surface-container-low">正在加载设置...</div>;
  if (loadError) return <div className="flex-1 overflow-auto p-8 bg-surface-container-low text-error">设置加载失败: {loadError}</div>;

  return (
    <div className="flex-1 overflow-auto p-8 bg-surface-container-low">
      <div className="max-w-5xl mx-auto space-y-4">
        <h2 className="text-lg font-semibold text-on-surface">全局设置</h2>
        {categories.map((category) => {
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
                </div>
                <div className="flex items-center gap-2">
                  {id === 'agent_settings' && (
                    <>
                      <button
                        disabled={agentInstalling}
                        onClick={handleAgentInstall}
                        className="px-3 py-1.5 text-xs rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest disabled:opacity-50 border border-outline-variant"
                        title="打开终端安装当前选中的 Agent CLI"
                      >
                        {agentInstalling ? '安装中...' : '安装'}
                      </button>
                      <button
                        disabled={agentTesting}
                        onClick={handleAgentTest}
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
                  <label><div className="mb-1">提取模式</div><select className="w-full px-3 py-2 rounded border" value={str(values.extraction_mode)} onChange={(e) => updateField(id, 'extraction_mode', e.target.value)}><option value="fast">fast</option><option value="agent">agent</option></select></label>
                  <label><div className="mb-1">Fast 模式提供商</div><select className="w-full px-3 py-2 rounded border" value={str(values.fast_provider)} onChange={(e) => applyProviderPreset('pipeline', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">Fast 模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.fast_model)} onChange={(e) => updateField(id, 'fast_model', e.target.value)} /></label>
                  <label><div className="mb-1">Fast API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.fast_api_key)} onChange={(e) => updateField(id, 'fast_api_key', e.target.value)} /></label>
                  <label><div className="mb-1">Fast Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.fast_base_url)} onChange={(e) => updateField(id, 'fast_base_url', e.target.value)} /></label>
                  <label className="md:col-span-2"><div className="mb-1">Fast Endpoint URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.fast_endpoint_url)} onChange={(e) => updateField(id, 'fast_endpoint_url', e.target.value)} /></label>
                  {str(values.extraction_mode) === 'agent' ? <div className="md:col-span-2 text-on-surface-variant">Agent 模式使用下方「Pipeline Agent」分类中配置的 Agent 后端进行三步提取（提取→消歧→笔记），耗时较长但质量更高。</div> : null}
                </div>
              )}

              {id === 'translation' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">翻译提供商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('translation', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">翻译模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label><div className="mb-1">API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} /></label>
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
                  <label><div className="mb-1">API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} /></label>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField(id, 'base_url', e.target.value)} /></label>
                </div>
              )}

              {id === 'pipeline_agent' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  {(() => {
                    const backend = str(values.backend) || 'codex';
                    const effortOptions = getEffortOptions(values, backend);
                    const currentEffort = str(values.reasoning_effort).toLowerCase();
                    const effectiveEffort = effortOptions.includes(currentEffort) ? currentEffort : (effortOptions[0] ?? '');
                    return (
                      <>
                  <label>
                    <div className="mb-1">Agent 后端</div>
                    <select
                      className="w-full px-3 py-2 rounded border"
                      value={str(values.backend)}
                      onChange={(e) => {
                        const nextBackend = e.target.value;
                        updateField(id, 'backend', nextBackend);
                        const nextOptions = getEffortOptions(values, nextBackend);
                        if (nextOptions.length > 0) {
                          updateField(id, 'reasoning_effort', nextOptions[0]);
                        }
                      }}
                    >
                      <option value="codex">Codex</option>
                      <option value="claude_code">Claude Code</option>
                      <option value="gemini_cli">Gemini CLI</option>
                    </select>
                  </label>
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('pipeline_agent', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label>
                    <div className="mb-1">思考深度</div>
                    <select
                      className="w-full px-3 py-2 rounded border"
                      value={effectiveEffort}
                      onChange={(e) => updateField(id, 'reasoning_effort', e.target.value)}
                      disabled={effortOptions.length === 0}
                    >
                      {effortOptions.length === 0 ? <option value="">不支持</option> : null}
                      {effortOptions.map((opt) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  </label>
                  <label><div className="mb-1">API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} /></label>
                  <label><div className="mb-1">Base URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.base_url)} onChange={(e) => updateField(id, 'base_url', e.target.value)} /></label>
                  <div className="md:col-span-2 text-on-surface-variant">Pipeline Agent 配置独立于 Chat Agent，用于论文提取任务。仅当提取模式选择「agent」时生效。</div>
                      </>
                    );
                  })()}
                </div>
              )}

              {id === 'embedding' && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                  <label><div className="mb-1">供应商</div><select className="w-full px-3 py-2 rounded border" value={str(values.provider)} onChange={(e) => applyProviderPreset('embedding', e.target.value)}>{presets.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.id})</option>)}</select></label>
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label><div className="mb-1">API Key</div><input className="w-full px-3 py-2 rounded border" type="password" value={str(values.api_key)} onChange={(e) => updateField(id, 'api_key', e.target.value)} /></label>
                  <label className="md:col-span-2"><div className="mb-1">Endpoint URL</div><input className="w-full px-3 py-2 rounded border" value={str(values.endpoint_url)} onChange={(e) => updateField(id, 'endpoint_url', e.target.value)} /></label>
                  <div className="md:col-span-2 text-on-surface-variant">文献向量嵌入提供商的配置。支持 OpenAI 兼容的 /embeddings 接口。常用模型：text-embedding-3-small (OpenAI)、embedding-3 (智谱)、BAAI/bge-m3 (SiliconFlow)。</div>
                </div>
              )}

              {id === 'agent_settings' && agentTestResult && (
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
    </div>
  );
}
