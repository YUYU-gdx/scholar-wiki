import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { GlobalSettingsPayload } from '../types';

type SectionState = {
  saving: boolean;
  message: string;
};

const EMPTY_STATE: SectionState = { saving: false, message: '' };

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function toText(value: unknown): string {
  if (Array.isArray(value) || (value && typeof value === 'object')) {
    try {
      return JSON.stringify(value);
    } catch {
      return '';
    }
  }
  return String(value ?? '');
}

function toTypedValue(raw: string, original: unknown): unknown {
  if (typeof original === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : original;
  }
  if (Array.isArray(original) || (original && typeof original === 'object')) {
    try {
      return JSON.parse(raw);
    } catch {
      return original;
    }
  }
  return raw;
}

function labelFromKey(key: string): string {
  const zhMap: Record<string, string> = {
    executor: '执行器',
    job_store_dsn: '任务存储 DSN',
    redis_url: 'Redis 地址',
    mineru_api_key_env: 'MinerU 密钥环境变量',
    mineru_base_url: 'MinerU Base URL',
    mineru_model_version: 'MinerU 模型版本',
    llm_provider: 'LLM 提供方',
    llm_model: 'LLM 模型',
    llm_api_key_env: 'LLM 密钥环境变量',
    llm_base_url: 'LLM Base URL',
    max_poll_seconds: '最大轮询秒数',
    poll_interval_seconds: '轮询间隔秒数',
    max_retries: '最大重试次数',
    retry_delays: '重试延迟',
    provider: '提供方',
    model: '模型',
    api_key: 'API Key',
    base_url: 'Base URL',
    endpoint_url: 'Endpoint URL',
    target_lang: '目标语言',
    default_library_id: '默认文献库 ID',
    registry_path: '注册表路径',
    workspaces_dir: '工作区目录',
    indexes_dir: '索引目录',
  };
  if (zhMap[key]) {
    return zhMap[key];
  }
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function SettingsView() {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [payload, setPayload] = useState<GlobalSettingsPayload | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [sectionState, setSectionState] = useState<Record<string, SectionState>>({});
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});

  const categories = useMemo(() => payload?.schema?.categories ?? [], [payload]);

  useEffect(() => {
    api.settings.getAll()
      .then((data) => {
        setPayload(data);
        setDrafts(data.settings ?? {});
      })
      .catch((err) => setLoadError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const updateField = (category: string, key: string, value: unknown) => {
    setDrafts((prev) => {
      const next = { ...prev };
      const section = { ...asRecord(next[category]) };
      section[key] = value;
      next[category] = section;
      return next;
    });
  };

  const saveCategory = async (category: string) => {
    const current = asRecord(drafts[category]);
    setSectionState((prev) => ({ ...prev, [category]: { saving: true, message: '' } }));
    try {
      const res = await api.settings.updateCategory(category, current);
      setDrafts((prev) => ({ ...prev, [category]: asRecord(res.config) }));
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: '保存成功。' } }));
    } catch (err) {
      setSectionState((prev) => ({ ...prev, [category]: { saving: false, message: `保存失败: ${(err as Error).message}` } }));
    }
  };

  if (loading) {
    return <div className="flex-1 overflow-auto p-8 bg-surface-container-low">正在加载设置...</div>;
  }

  if (loadError) {
    return <div className="flex-1 overflow-auto p-8 bg-surface-container-low text-error">设置加载失败: {loadError}</div>;
  }

  return (
    <div className="flex-1 overflow-auto p-8 bg-surface-container-low">
      <div className="max-w-5xl mx-auto space-y-4">
        <h2 className="text-lg font-semibold text-on-surface">全局设置</h2>
        {categories.length === 0 ? (
          <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-5 text-sm text-on-surface-variant">
            后端未返回任何可用设置分类。
            <pre className="mt-3 whitespace-pre-wrap break-all text-xs">{JSON.stringify(payload, null, 2)}</pre>
          </div>
        ) : null}
        {categories.map((category) => {
          const id = category.id;
          const state = sectionState[id] ?? EMPTY_STATE;
          const values = asRecord(drafts[id]);
          const fieldDefs = Array.isArray(category.fields) ? category.fields : [];
          const fieldKeys = fieldDefs.length > 0
            ? fieldDefs.map((f) => f.key)
            : Object.keys(values);
          return (
            <div key={id} className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-5 space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-base font-semibold text-on-surface">{category.title}</div>
                  {category.restart_required ? (
                    <div className="text-xs text-on-surface-variant">该配置更新后需要重启生效。</div>
                  ) : null}
                </div>
                <button
                  disabled={state.saving}
                  onClick={() => saveCategory(id)}
                  className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50"
                >
                  {state.saving ? '保存中...' : '保存'}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {fieldKeys.map((key) => {
                  const meta = fieldDefs.find((f) => f.key === key);
                  const value = values[key];
                  const secretKey = `${id}.${key}`;
                  const isSensitive = Boolean(meta?.sensitive || key.toLowerCase().includes('api_key'));
                  const inputType = isSensitive && !visibleSecrets[secretKey] ? 'password' : 'text';
                  const textValue = toText(value);
                  return (
                    <label key={key} className="text-sm md:col-span-1">
                      <div className="mb-1 text-on-surface-variant flex items-center gap-2">
                        <span>{labelFromKey(key)}</span>
                        {isSensitive ? (
                          <button
                            type="button"
                            className="text-xs underline"
                            onClick={() => setVisibleSecrets((prev) => ({ ...prev, [secretKey]: !prev[secretKey] }))}
                          >
                            {visibleSecrets[secretKey] ? '隐藏' : '编辑'}
                          </button>
                        ) : null}
                      </div>
                      {meta?.type === 'select' && Array.isArray(meta.options) ? (
                        <select
                          className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container"
                          value={textValue}
                          onChange={(e) => updateField(id, key, e.target.value)}
                        >
                          {meta.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                        </select>
                      ) : (
                        <input
                          className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container"
                          type={inputType}
                          value={textValue}
                          onChange={(e) => updateField(id, key, toTypedValue(e.target.value, value))}
                        />
                      )}
                    </label>
                  );
                })}
              </div>
              {state.message ? <div className="text-sm text-on-surface-variant">{state.message}</div> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
