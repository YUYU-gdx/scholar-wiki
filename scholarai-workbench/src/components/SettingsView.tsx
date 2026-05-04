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

export default function SettingsView() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [payload, setPayload] = useState<GlobalSettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [sectionState, setSectionState] = useState<Record<string, SectionState>>({});

  const categories = useMemo(() => {
    const raw = payload?.schema?.categories ?? [];
    return raw
      .map((c) => ({ ...c, id: c.id === 'codex_global' ? 'agent_settings' : c.id }))
      .filter((c) => c.id === 'pipeline' || c.id === 'translation' || c.id === 'agent_settings');
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

  const applyProviderPreset = (category: 'pipeline' | 'translation', providerId: string) => {
    const values = asRecord(drafts[category]);
    const presets = (values.provider_presets as ProviderPreset[]) || [];
    const hit = presets.find((p) => p.id === providerId);
    if (!hit) return;
    if (category === 'pipeline') {
      updateField('pipeline', 'fast_provider', providerId);
      updateField('pipeline', 'fast_base_url', hit.base_url);
      updateField('pipeline', 'fast_endpoint_url', `${hit.base_url.replace(/\/$/, '')}/v1/chat/completions`);
      return;
    }
    updateField('translation', 'provider', providerId);
    updateField('translation', 'base_url', hit.base_url);
    updateField('translation', 'endpoint_url', `${hit.base_url.replace(/\/$/, '')}/v1/chat/completions`);
  };

  const saveCategory = async (category: string) => {
    const current = asRecord(drafts[category]);
    const { provider_presets: _drop1, recommendation: _drop2, ...body } = current;
    setSectionState((prev) => ({ ...prev, [category]: { saving: true, message: '' } }));
    try {
      const res = await api.settings.updateCategory(category, body);
      setDrafts((prev) => ({ ...prev, [category]: asRecord(res.config) }));
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: '保存成功。' } }));
    } catch (err) {
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: `保存失败: ${(err as Error).message}` } }));
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
                <button disabled={state.saving} onClick={() => saveCategory(id)} className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50">
                  {state.saving ? '保存中...' : '保存'}
                </button>
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
                  {str(values.extraction_mode) === 'agent' ? <div className="md:col-span-2 text-on-surface-variant">Agent 模式暂只预留接口，后续扩展。</div> : null}
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
                  <label><div className="mb-1">模型</div><input className="w-full px-3 py-2 rounded border" value={str(values.model)} onChange={(e) => updateField(id, 'model', e.target.value)} /></label>
                  <label><div className="mb-1">审批策略</div><input className="w-full px-3 py-2 rounded border" value={str(values.approval_policy)} onChange={(e) => updateField(id, 'approval_policy', e.target.value)} /></label>
                  <label><div className="mb-1">沙箱模式</div><input className="w-full px-3 py-2 rounded border" value={str(values.sandbox_mode)} onChange={(e) => updateField(id, 'sandbox_mode', e.target.value)} /></label>
                  <label><div className="mb-1">超时秒数</div><input className="w-full px-3 py-2 rounded border" value={str(values.timeout_seconds)} onChange={(e) => updateField(id, 'timeout_seconds', Number(e.target.value) || 0)} /></label>
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
