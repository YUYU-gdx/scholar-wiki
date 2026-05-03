import { useEffect, useState } from 'react';
import { api } from '../api';
import type { TranslationProviderConfig } from '../types';

const DEFAULT_CFG: TranslationProviderConfig = {
  provider: 'deepseek',
  model: 'deepseek-v4-flash',
  api_key: '',
  base_url: 'https://api.deepseek.com',
  endpoint_url: 'https://api.deepseek.com/v1/chat/completions',
  target_lang: 'zh',
};

export default function SettingsView() {
  const [cfg, setCfg] = useState<TranslationProviderConfig>(DEFAULT_CFG);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    api.chat.getTranslationProviderConfig()
      .then((data) => setCfg({ ...DEFAULT_CFG, ...data }))
      .catch(() => setCfg(DEFAULT_CFG));
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage('');
    try {
      const res = await api.chat.saveTranslationProviderConfig(cfg);
      setCfg({ ...DEFAULT_CFG, ...res.config });
      setMessage('翻译配置已保存');
    } catch (e) {
      setMessage(`保存失败：${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setMessage('');
    try {
      const res = await api.chat.translate('This is a translation test.', cfg);
      setMessage(`测试成功：${res.translated_text}`);
    } catch (e) {
      setMessage(`测试失败：${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto p-8 bg-surface-container-low">
      <div className="max-w-3xl mx-auto bg-surface-container-lowest border border-outline-variant rounded-2xl p-6 space-y-5">
        <h2 className="text-lg font-semibold text-on-surface">Settings / 翻译设置</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="text-sm">
            <div className="mb-1 text-on-surface-variant">Provider</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" value={cfg.provider} onChange={(e) => setCfg((p) => ({ ...p, provider: e.target.value }))} />
          </label>
          <label className="text-sm">
            <div className="mb-1 text-on-surface-variant">Model</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" value={cfg.model} onChange={(e) => setCfg((p) => ({ ...p, model: e.target.value }))} />
          </label>
          <label className="text-sm md:col-span-2">
            <div className="mb-1 text-on-surface-variant">API Key</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" type="password" value={cfg.api_key} onChange={(e) => setCfg((p) => ({ ...p, api_key: e.target.value }))} />
          </label>
          <label className="text-sm">
            <div className="mb-1 text-on-surface-variant">Base URL</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" value={cfg.base_url} onChange={(e) => setCfg((p) => ({ ...p, base_url: e.target.value }))} />
          </label>
          <label className="text-sm">
            <div className="mb-1 text-on-surface-variant">Endpoint URL</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" value={cfg.endpoint_url} onChange={(e) => setCfg((p) => ({ ...p, endpoint_url: e.target.value }))} />
          </label>
          <label className="text-sm">
            <div className="mb-1 text-on-surface-variant">Target Language</div>
            <input className="w-full px-3 py-2 rounded border border-outline-variant bg-surface-container" value={cfg.target_lang} onChange={(e) => setCfg((p) => ({ ...p, target_lang: e.target.value }))} />
          </label>
        </div>
        <div className="flex items-center gap-3">
          <button disabled={saving} onClick={save} className="px-4 py-2 rounded bg-secondary text-on-secondary disabled:opacity-50">保存</button>
          <button disabled={testing} onClick={test} className="px-4 py-2 rounded border border-outline-variant hover:bg-surface-container disabled:opacity-50">测试翻译</button>
          {message && <div className="text-sm text-on-surface-variant">{message}</div>}
        </div>
      </div>
    </div>
  );
}

