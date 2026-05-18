import type {
  GraphOverview,
  GraphFull,
  NeighborhoodResponse,
  SearchResponse,
  SemanticVariableNeighborsResponse,
  SemanticVariableSearchResponse,
  PaperDetail,
  VariableDetail,
  ChatSession,
  ChatMessage,
  SendMessageResponse,
  PipelineJob,
  PipelineJobList,
  PipelineBatchSubmitResponse,
  PipelineBatchActionResponse,
  LibrariesResponse,
  LiteraturePapersResponse,
  LiteratureSearchResponse,
  LiteratureAnswerResponse,
  WorkspaceLayout,
  TranslationProviderConfig,
  TranslateResponse,
  TranslateJobSubmitResponse,
  TranslateJobStatusResponse,
  GlobalSettingsPayload,
  AgentTemplatePayload,
  ZoteroScanResponse,
  ZoteroImportResponse,
} from './types';

// In Electron (file:// protocol), API_BASE must point to the backend.
// In Vite dev mode, the proxy at port 3000 handles routing so base is empty.
const API_BASE = (() => {
  const w = window as unknown as { desktopShell?: { getBackendUrlSync?: () => string } };
  if (w.desktopShell?.getBackendUrlSync) return w.desktopShell.getBackendUrlSync();
  return '';
})();

async function jsonFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers as Record<string, string> || {}) },
    ...options,
  });
  const text = await resp.text();
  let payload: unknown = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }
  if (!resp.ok) {
    const errPayload = payload as Record<string, unknown>;
    throw new Error((errPayload?.error as string) || `http_${resp.status}`);
  }
  return payload as T;
}

export const api = {
  graph: {
    overview(libraryId: string = ''): Promise<GraphOverview> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<GraphOverview>(`/graph/overview${params}`);
    },
    full(libraryId: string = ''): Promise<GraphFull> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<GraphFull>(`/graph/full${params}`);
    },
    search(query: string, mode: string = 'variable', limit: number = 20, libraryId: string = ''): Promise<SearchResponse> {
      const params = new URLSearchParams({ query, mode, limit: String(limit) });
      if (libraryId) params.set('library_id', libraryId);
      return jsonFetch<SearchResponse>(`/graph/search?${params}`);
    },
    neighborhood(nodeId: string, hops: number = 1, limitNodes: number = 350, limitEdges: number = 900, libraryId: string = ''): Promise<NeighborhoodResponse> {
      const params = new URLSearchParams({ node_id: nodeId, hops: String(hops), limit_nodes: String(limitNodes), limit_edges: String(limitEdges) });
      if (libraryId) params.set('library_id', libraryId);
      return jsonFetch<NeighborhoodResponse>(`/graph/neighborhood?${params}`);
    },
    async semanticVariableSearch(query: string, topK: number, libraryIds: string[]): Promise<SemanticVariableSearchResponse> {
      const body = JSON.stringify({ query, top_k: topK, library_ids: libraryIds });
      try {
        return await jsonFetch<SemanticVariableSearchResponse>('/graph/semantic-variables/search', { method: 'POST', body });
      } catch (err) {
        if (String((err as Error)?.message || '') !== 'http_404') throw err;
        return jsonFetch<SemanticVariableSearchResponse>('/v1/graph/semantic-variables/search', { method: 'POST', body });
      }
    },
    async semanticVariableNeighbors(variableName: string, topK: number, libraryIds: string[]): Promise<SemanticVariableNeighborsResponse> {
      const body = JSON.stringify({ variable_name: variableName, top_k: topK, library_ids: libraryIds });
      try {
        return await jsonFetch<SemanticVariableNeighborsResponse>('/graph/semantic-variables/neighbors', { method: 'POST', body });
      } catch (err) {
        if (String((err as Error)?.message || '') !== 'http_404') throw err;
        return jsonFetch<SemanticVariableNeighborsResponse>('/v1/graph/semantic-variables/neighbors', { method: 'POST', body });
      }
    },
    paper(id: string, libraryId: string = ''): Promise<PaperDetail> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<PaperDetail>(`/paper/${encodeURIComponent(id)}${params}`);
    },
    variable(id: string, libraryId: string = ''): Promise<VariableDetail> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<VariableDetail>(`/variable/${encodeURIComponent(id)}${params}`);
    },
    paperFiles(id: string, libraryId: string = ''): Promise<import('./types').PaperFiles> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<import('./types').PaperFiles>(`/paper/${encodeURIComponent(id)}/files${params}`);
    },
    deletePaper(id: string, libraryId: string = ''): Promise<Record<string, unknown>> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch<Record<string, unknown>>(`/paper/${encodeURIComponent(id)}${params}`, { method: 'DELETE' });
    },
  },

  chat: {
    listSessions(libraryId: string = ''): Promise<{ sessions: ChatSession[] }> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch(`/chat/sessions${params}`);
    },
    getSession(sessionId: string, libraryId: string = ''): Promise<{ session: ChatSession; messages: ChatMessage[] }> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}${params}`);
    },
    createSession(title: string, libraryId: string = '', defaultMode: string = 'agent'): Promise<ChatSession> {
      return jsonFetch('/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({ title, library_id: libraryId, default_mode: defaultMode }),
      });
    },
    deleteSession(sessionId: string, libraryId: string = ''): Promise<void> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}${params}`, { method: 'DELETE' }).then(() => {});
    },
    restoreSession(sessionId: string, libraryId: string = ''): Promise<unknown> {
      const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : '';
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}/restore${params}`, { method: 'POST' });
    },
    sendMessage(sessionId: string, content: string, libraryId: string = '', mode: string = 'agent', provider: string = '', model: string = 'codex-local', stream: boolean = true): Promise<SendMessageResponse> {
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content, library_id: libraryId, mode, provider, model, stream }),
      });
    },
    streamEvents(sessionId: string, messageId: string, cursor: number = 0): EventSource {
      const url = `${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}/stream?message_id=${encodeURIComponent(messageId)}&cursor=${cursor}`;
      return new EventSource(url);
    },
    getProviderConfig(): Promise<Record<string, unknown>> {
      return jsonFetch('/chat/provider-config');
    },
    saveProviderConfig(config: Record<string, unknown>): Promise<unknown> {
      return jsonFetch('/chat/provider-config', {
        method: 'POST',
        body: JSON.stringify(config),
      });
    },
    testProvider(provider: string, model: string, prompt: string): Promise<unknown> {
      return jsonFetch('/chat/provider-test', {
        method: 'POST',
        body: JSON.stringify({ provider, model, prompt }),
      });
    },
    getTranslationProviderConfig(): Promise<TranslationProviderConfig> {
      return jsonFetch('/chat/translation-provider-config');
    },
    saveTranslationProviderConfig(config: Partial<TranslationProviderConfig>): Promise<{ ok: boolean; config: TranslationProviderConfig }> {
      return jsonFetch('/chat/translation-provider-config', {
        method: 'POST',
        body: JSON.stringify(config),
      });
    },
    translate(
      text: string,
      options: Partial<TranslationProviderConfig> = {},
      compareByParagraph: boolean = false,
    ): Promise<TranslateResponse> {
      return jsonFetch('/chat/translate', {
        method: 'POST',
        body: JSON.stringify({
          text,
          target_lang: options.target_lang || 'zh',
          provider: options.provider || 'deepseek',
          model: options.model || 'deepseek-v4-flash',
          api_key: options.api_key || '',
          base_url: options.base_url || '',
          endpoint_url: options.endpoint_url || '',
          compare_by_paragraph: compareByParagraph,
        }),
      });
    },
    submitTranslateJob(
      text: string,
      options: Partial<TranslationProviderConfig> = {},
    ): Promise<TranslateJobSubmitResponse> {
      return jsonFetch('/chat/translate/jobs', {
        method: 'POST',
        body: JSON.stringify({
          text,
          target_lang: options.target_lang || 'zh',
          provider: options.provider || 'deepseek',
          model: options.model || 'deepseek-v4-flash',
          api_key: options.api_key || '',
          base_url: options.base_url || '',
          endpoint_url: options.endpoint_url || '',
        }),
      });
    },
    getTranslateJob(jobId: string): Promise<TranslateJobStatusResponse> {
      return jsonFetch(`/chat/translate/jobs/${encodeURIComponent(jobId)}`);
    },
    getCodexConfig(): Promise<Record<string, unknown>> {
      return jsonFetch('/chat/codex/config');
    },
    saveCodexConfig(config: Record<string, unknown>): Promise<unknown> {
      return jsonFetch('/chat/codex/config', {
        method: 'POST',
        body: JSON.stringify(config),
      });
    },
    getCodexHealth(): Promise<Record<string, unknown>> {
      return jsonFetch('/chat/codex/health');
    },
    getCodexPreflight(libraryId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/chat/codex/preflight?library_id=${encodeURIComponent(libraryId)}`);
    },
  },

  literature: {
    listLibraries(): Promise<LibrariesResponse> {
      return jsonFetch('/literature/libraries');
    },
    listLibraryPapers(libraryId: string): Promise<LiteraturePapersResponse> {
      return jsonFetch(`/literature/libraries/${encodeURIComponent(libraryId)}/papers`);
    },
    createLibrary(libraryId: string, workspaceRoot: string = '', setDefault: boolean = true): Promise<Record<string, unknown>> {
      return jsonFetch('/literature/libraries', {
        method: 'POST',
        body: JSON.stringify({
          library_id: libraryId,
          workspace_root: workspaceRoot,
          set_default: setDefault,
        }),
      });
    },
    deleteLibrary(libraryId: string, deleteWorkspaceData: boolean = true): Promise<Record<string, unknown>> {
      const params = new URLSearchParams({ delete_workspace_data: String(deleteWorkspaceData) });
      return jsonFetch(`/literature/libraries/${encodeURIComponent(libraryId)}?${params}`, {
        method: 'DELETE',
      });
    },
    search(query: string, libraryId: string, topK: number = 20, levels: string = 'sentence', keywordWeight: number = 0.4, ragWeight: number = 0.6): Promise<LiteratureSearchResponse> {
      const params = new URLSearchParams({ query, library_id: libraryId, top_k: String(topK), levels, keyword_weight: String(keywordWeight), rag_weight: String(ragWeight) });
      return jsonFetch(`/literature/search?${params}`);
    },
    answer(query: string, libraryId: string, topK: number = 5, levels: string[] = ['sentence'], keywordWeight: number = 0.4, ragWeight: number = 0.6): Promise<LiteratureAnswerResponse> {
      return jsonFetch('/literature/answer', {
        method: 'POST',
        body: JSON.stringify({ query, library_id: libraryId, top_k: topK, levels, keyword_weight: keywordWeight, rag_weight: ragWeight }),
      });
    },
  },

  zotero: {
    scan(dataDir: string): Promise<ZoteroScanResponse> {
      return jsonFetch('/literature/zotero/scan', {
        method: 'POST',
        body: JSON.stringify({ data_dir: dataDir }),
      });
    },
    importItems(dataDir: string, itemIds: number[], libraryId: string): Promise<ZoteroImportResponse> {
      return jsonFetch('/literature/zotero/import', {
        method: 'POST',
        body: JSON.stringify({ data_dir: dataDir, item_ids: itemIds, library_id: libraryId }),
      });
    },
  },

  pipeline: {
    listJobs(page: number = 1, pageSize: number = 50, status?: string, libraryId?: string, sort?: string): Promise<PipelineJobList> {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (status) params.set('status', status);
      if (libraryId) params.set('library_id', libraryId);
      if (sort) params.set('sort', sort);
      return jsonFetch(`/v1/jobs?${params}`);
    },
    getJob(jobId: string): Promise<PipelineJob> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}`);
    },
    getResult(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}/result`);
    },
    submitJob(file: File, libraryId: string, options?: Record<string, unknown>): Promise<PipelineJob> {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('library_id', libraryId);
      if (options) formData.append('options', JSON.stringify(options));
      return fetch(`${API_BASE}/v1/pipeline/parse-extract`, { method: 'POST', body: formData }).then(async (resp) => {
        const payload = await resp.json();
        if (!resp.ok) throw new Error(payload.error || `http_${resp.status}`);
        return payload as PipelineJob;
      });
    },
    submitJobsBatch(files: File[], libraryId: string): Promise<PipelineBatchSubmitResponse> {
      const formData = new FormData();
      files.forEach((file) => formData.append('files', file));
      formData.append('library_id', libraryId);
      return fetch(`${API_BASE}/v1/pipeline/parse-extract/batch`, { method: 'POST', body: formData }).then(async (resp) => {
        const payload = await resp.json();
        if (!resp.ok) {
          const error = String((payload as Record<string, unknown>)?.error || `http_${resp.status}`);
          const rejected = Array.isArray((payload as Record<string, unknown>)?.rejected)
            ? ((payload as Record<string, unknown>).rejected as Array<Record<string, unknown>>)
            : [];
          const rejectedDetail = rejected
            .map((item) => {
              const fileName = String(item?.file_name || 'unknown_file');
              const reason = String(item?.error || 'unknown_error');
              return `${fileName}: ${reason}`;
            })
            .join('\n');
          const detail = rejectedDetail ? `\n${rejectedDetail}` : '';
          throw new Error(`${error}${detail}`);
        }
        return payload as PipelineBatchSubmitResponse;
      });
    },
    cancelJob(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    },
    retryJob(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' });
    },
    deleteJob(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
    },
    batchOperateJobs(action: 'cancel' | 'retry' | 'delete', jobIds: string[]): Promise<PipelineBatchActionResponse> {
      const formData = new FormData();
      formData.append('action', action);
      formData.append('job_ids', JSON.stringify(jobIds));
      return fetch(`${API_BASE}/v1/jobs/batch`, { method: 'POST', body: formData }).then(async (resp) => {
        const payload = await resp.json();
        if (!resp.ok && resp.status !== 207) throw new Error(payload.error || `http_${resp.status}`);
        return payload as PipelineBatchActionResponse;
      });
    },
    streamJobEvents(jobId: string): EventSource {
      return new EventSource(`${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}/events`);
    },
    streamJobAgentEvents(jobId: string, cursor: number = 0): EventSource {
      return new EventSource(`${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}/agent-events?cursor=${Math.max(0, cursor)}`);
    },
  },

  workspace: {
    listLayouts(): Promise<WorkspaceLayout[]> {
      return jsonFetch('/api/v2/workspace/layouts');
    },
    getLayout(name: string = 'default'): Promise<WorkspaceLayout> {
      return jsonFetch(`/api/v2/workspace/layout?name=${encodeURIComponent(name)}`);
    },
    saveLayout(name: string, layout: Record<string, unknown>): Promise<unknown> {
      return jsonFetch('/api/v2/workspace/layout', {
        method: 'POST',
        body: JSON.stringify({ name, layout }),
      });
    },
  },

  settings: {
    getAll(): Promise<GlobalSettingsPayload> {
      return jsonFetch('/settings');
    },
    getSchema(): Promise<GlobalSettingsPayload['schema']> {
      return jsonFetch('/settings/schema');
    },
    updateCategory(category: string, payload: Record<string, unknown>): Promise<{ ok: boolean; category: string; config: Record<string, unknown> }> {
      return jsonFetch(`/settings/${encodeURIComponent(category)}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },
    testApiKey(category: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> {
      return jsonFetch('/settings/test-key', {
        method: 'POST',
        body: JSON.stringify({ category, config: payload }),
      });
    },
    getAgentTemplate(target: string): Promise<AgentTemplatePayload> {
      return jsonFetch(`/settings/agent-templates/${encodeURIComponent(target)}`);
    },
    saveAgentTemplate(target: string, content: string): Promise<AgentTemplatePayload> {
      return jsonFetch(`/settings/agent-templates/${encodeURIComponent(target)}`, {
        method: 'PUT',
        body: JSON.stringify({ content }),
      });
    },
  },

  agent: {
    installInfo(agentId: string): Promise<{
      agent_id: string;
      command: string;
      binary: string;
      verify: string;
      display_name: string;
      not_available?: boolean;
    }> {
      return jsonFetch('/chat/agent/install-info', {
        method: 'POST',
        body: JSON.stringify({ agent_id: agentId }),
      });
    },
    test(agentId: string): Promise<{
      agent_id: string;
      ok: boolean;
      passed_count: number;
      failed_count: number;
      checks: Array<{
        name: string;
        passed: boolean;
        stage: string;
        suggestion?: string;
        binary?: string;
        version?: string;
        path?: string;
        error?: string;
      }>;
      checked_at: string;
    }> {
      return jsonFetch('/chat/agent/test', {
        method: 'POST',
        body: JSON.stringify({ agent_id: agentId }),
      });
    },
  },
};
