import type {
  GraphOverview,
  GraphFull,
  NeighborhoodResponse,
  SearchResponse,
  PaperDetail,
  VariableDetail,
  ChatSession,
  ChatMessage,
  SendMessageResponse,
  PipelineJob,
  PipelineJobList,
  LibrariesResponse,
  LiteratureSearchResponse,
  LiteratureAnswerResponse,
  WorkspaceLayout,
} from './types';

const API_BASE = '';

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
  },

  chat: {
    listSessions(libraryId: string): Promise<{ sessions: ChatSession[] }> {
      return jsonFetch(`/chat/sessions?library_id=${encodeURIComponent(libraryId)}`);
    },
    getSession(sessionId: string, libraryId: string): Promise<{ session: ChatSession; messages: ChatMessage[] }> {
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}?library_id=${encodeURIComponent(libraryId)}`);
    },
    createSession(title: string, libraryId: string, defaultMode: string = 'agent'): Promise<ChatSession> {
      return jsonFetch('/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({ title, library_id: libraryId, default_mode: defaultMode }),
      });
    },
    deleteSession(sessionId: string, libraryId: string): Promise<void> {
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}?library_id=${encodeURIComponent(libraryId)}`, { method: 'DELETE' }).then(() => {});
    },
    restoreSession(sessionId: string, libraryId: string): Promise<unknown> {
      return jsonFetch(`/chat/sessions/${encodeURIComponent(sessionId)}/restore?library_id=${encodeURIComponent(libraryId)}`, { method: 'POST' });
    },
    sendMessage(sessionId: string, content: string, libraryId: string, mode: string = 'agent', provider: string = 'codex', model: string = 'codex-local', stream: boolean = true): Promise<SendMessageResponse> {
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
    importPaper(manifestPath: string, libraryId: string, options?: Record<string, unknown>): Promise<Record<string, unknown>> {
      return jsonFetch('/literature/import', {
        method: 'POST',
        body: JSON.stringify({ manifest_path: manifestPath, library_id: libraryId, options: options || {} }),
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
    cancelJob(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    },
    retryJob(jobId: string): Promise<Record<string, unknown>> {
      return jsonFetch(`/v1/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' });
    },
    streamJobEvents(jobId: string): EventSource {
      return new EventSource(`${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}/events`);
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
};