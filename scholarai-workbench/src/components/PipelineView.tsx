import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { CloudUpload, FileText, RefreshCw, XCircle, Info, Terminal, Trash2, ChevronDown, Database } from 'lucide-react';
import ZoteroImportModal from './ZoteroImportModal';
import { useApp } from '../app-context';
import { api } from '../api';
import type { PipelineAgentEvent, PipelineJob } from '../types';

const STAGE_OPTIONS = [
  { value: '', label: '全部阶段' },
  { value: 'accepted', label: '已接受' },
  { value: 'parse_pdf', label: '解析 PDF' },
  { value: 'materialize_paper', label: '文献向量化中' },
  { value: 'extract_entities', label: '提取实体' },
  { value: 'finalize', label: '完成' },
] as const;

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
] as const;

type JobLogRow = { time: string; level: 'info' | 'warn' | 'error'; text: string; detail?: string };

function formatTs(ts?: string): string {
  if (!ts) return '-';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
}

function parseMaybeJson(raw: unknown): Record<string, unknown> | null {
  if (raw && typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw !== 'string' || !raw.trim()) return null;
  try {
    const v = JSON.parse(raw);
    if (v && typeof v === 'object') return v as Record<string, unknown>;
  } catch {
    return null;
  }
  return null;
}

function buildJobLogs(job: PipelineJob): JobLogRow[] {
  const rows: JobLogRow[] = [];
  rows.push({ time: formatTs(job.created_at), level: 'info', text: '[解析] 已上传并创建任务' });
  rows.push({ time: formatTs(job.updated_at), level: 'info', text: `[${job.stage_code || job.stage || 'stage'}] 当前进度 ${job.progress ?? 0}%` });

  const options = parseMaybeJson((job as unknown as Record<string, unknown>).options_json);
  const extractionMode = String(options?.extraction_mode || '').trim().toLowerCase();
  if (extractionMode === 'agent') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: '[agent提取] 已提交任务' });
  } else if (extractionMode === 'fast') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: '[fast提取] 已提交任务' });
  }

  const stage = job.stage_code || job.stage || '';
  if (stage === 'parse_pdf' && (job.progress ?? 0) < 45 && job.status === 'running') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: '[解析] 轮询中' });
  }
  if (stage === 'extract_entities' && job.status === 'running') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: '[提取] 正在执行抽取流程' });
  }
  if (stage === 'finalize' && job.status === 'running') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: '[入库] 正在整理结果并构建图谱' });
  }

  const importCount = Number((job as unknown as Record<string, unknown>).imported_paper_count ?? 0);
  if (job.status === 'completed') {
    rows.push({ time: formatTs(job.updated_at), level: 'info', text: `[完成] 提取完成，导入 ${Number.isFinite(importCount) ? importCount : 0} 篇` });
  }
  if (job.status === 'failed') {
    rows.push({ time: formatTs(job.updated_at), level: 'error', text: `[失败] ${job.error_code || 'pipeline_failed'}: ${job.error_detail || '未知错误'}` });
  }
  if (job.status === 'cancelled') {
    rows.push({ time: formatTs(job.updated_at), level: 'warn', text: '[取消] 任务已取消' });
  }

  return rows;
}

function flattenText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(flattenText).filter(Boolean).join(' ');
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '';
    }
  }
  return String(value ?? '');
}

function agentEventToLogRow(e: PipelineAgentEvent): JobLogRow {
  const t = formatTs(e.ts);
  const method = String(e.method || '');
  const params = e.params || {};
  if (method === 'system/init') {
    const p = params as Record<string, unknown>;
    return { time: t, level: 'info', text: '会话初始化', detail: `session_id=${String(p.session_id || '')}\nmodel=${String(p.model || '')}` };
  }
  if (method === 'item/agentMessage/delta') {
    const delta = flattenText((params as Record<string, unknown>).delta);
    return { time: t, level: 'info', text: '模型输出增量', detail: delta || '（空增量）' };
  }
  if (method === 'item/started') {
    const item = ((params as Record<string, unknown>).item || {}) as Record<string, unknown>;
    return {
      time: t,
      level: 'info',
      text: `步骤开始：${String(item.tool || item.type || '未知')}`,
      detail: flattenText(item.arguments || {}),
    };
  }
  if (method === 'item/completed') {
    const item = ((params as Record<string, unknown>).item || {}) as Record<string, unknown>;
    const status = String(item.status || 'completed');
    const lvl: JobLogRow['level'] = status === 'failed' ? 'error' : 'info';
    return {
      time: t,
      level: lvl,
      text: `步骤完成：${String(item.tool || item.type || '未知')}（${status}）`,
      detail: flattenText(item.result || {}),
    };
  }
  if (method === 'turn/completed') {
    return { time: t, level: 'info', text: '回合完成', detail: flattenText(params) };
  }
  if (method === 'item/thinking/delta') {
    return { time: t, level: 'info', text: '思考中', detail: flattenText((params as Record<string, unknown>).thinking) };
  }
  return { time: t, level: 'info', text: method || 'event', detail: flattenText(params) };
}

export default function PipelineView() {
  const PAGE_SIZE = 25;
  const { activeLibraryId, pipelineJobs, setPipelineJobs } = useApp();
  const [page, setPage] = useState(1);
  const [totalJobs, setTotalJobs] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [showZoteroModal, setShowZoteroModal] = useState(false);
  const [sseLog, setSseLog] = useState<Array<{ time: string; type: string; msg: string }>>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const sseRef = useRef<EventSource | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const [selectedJob, setSelectedJob] = useState<PipelineJob | null>(null);
  const [logJob, setLogJob] = useState<PipelineJob | null>(null);
  const [liveJobLogs, setLiveJobLogs] = useState<JobLogRow[]>([]);
  const [expandedLogItems, setExpandedLogItems] = useState<Record<string, boolean>>({});
  const [liveLogConnected, setLiveLogConnected] = useState(false);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
  const agentLogSseRef = useRef<EventSource | null>(null);
  const autoReconnectedRef = useRef(false);
  const completedDispatchedRef = useRef<Set<string>>(new Set());

  const fetchJobs = useCallback(async () => {
    try {
      const res = await api.pipeline.listJobs(page, PAGE_SIZE, statusFilter || undefined, activeLibraryId);
      const filtered = (res.jobs || []).filter((j) => !stageFilter || (j.stage_code || j.stage || '') === stageFilter);
      setPipelineJobs(filtered);
      setTotalJobs(Number(res.total || 0));
      for (const j of filtered) {
        if (j.status === 'completed' && !completedDispatchedRef.current.has(j.job_id)) {
          completedDispatchedRef.current.add(j.job_id);
          window.dispatchEvent(new CustomEvent('pipeline-completed', { detail: { libraryId: j.library_id || activeLibraryId } }));
        }
      }
      if (!autoReconnectedRef.current && !sseRef.current) {
        autoReconnectedRef.current = true;
        const running = filtered.filter((j) => j.status === 'queued' || j.status === 'running');
        if (running.length > 0) {
          streamJobEvents(running[0].job_id);
        }
      }
    } catch { /* ignore */ }
  }, [page, statusFilter, stageFilter, activeLibraryId, setPipelineJobs]);

  const totalPages = Math.max(1, Math.ceil(totalJobs / PAGE_SIZE));

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

  useEffect(() => {
    setSelectedJobIds((prev) => {
      const visible = new Set(pipelineJobs.map((j) => j.job_id));
      const next = new Set<string>();
      prev.forEach((id) => {
        if (visible.has(id)) next.add(id);
      });
      return next;
    });
  }, [pipelineJobs]);

  useEffect(() => {
    const hasActive = pipelineJobs.some((j) => j.status === 'queued' || j.status === 'running');
    if (!hasActive) return;
    const timer = window.setInterval(() => {
      fetchJobs();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [pipelineJobs, fetchJobs]);

  useEffect(() => {
    return () => {
      if (sseRef.current) {
        sseRef.current.close();
        sseRef.current = null;
        setSseConnected(false);
      }
      if (agentLogSseRef.current) {
        agentLogSseRef.current.close();
        agentLogSseRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!logJob?.job_id) {
      if (agentLogSseRef.current) {
        agentLogSseRef.current.close();
        agentLogSseRef.current = null;
      }
      setLiveLogConnected(false);
      setLiveJobLogs([]);
      return;
    }
    setLiveJobLogs(buildJobLogs(logJob));
    setExpandedLogItems({});
    const es = api.pipeline.streamJobAgentEvents(logJob.job_id, 0);
    agentLogSseRef.current = es;
    setLiveLogConnected(true);

    es.addEventListener('agent_event', (evt) => {
      try {
        const parsed = JSON.parse((evt as MessageEvent).data || '{}') as PipelineAgentEvent;
        setLiveJobLogs((prev) => [...prev, agentEventToLogRow(parsed)].slice(-800));
      } catch {
        /* ignore */
      }
    });
    es.addEventListener('agent_done', () => {
      setLiveLogConnected(false);
    });
    es.onerror = () => {
      setLiveLogConnected(false);
      es.close();
      if (agentLogSseRef.current === es) agentLogSseRef.current = null;
    };

    return () => {
      es.close();
      if (agentLogSseRef.current === es) agentLogSseRef.current = null;
      setLiveLogConnected(false);
    };
  }, [logJob?.job_id]);

  const refresh = async () => {
    setRefreshing(true);
    await fetchJobs();
    setRefreshing(false);
  };

  const deleteJob = async (jobId: string, fileName: string) => {
    if (!confirm(`删除任务「${fileName || jobId.slice(0, 12)}」？`)) return;
    try {
      await api.pipeline.deleteJob(jobId);
      setPipelineJobs((prev) => prev.filter((j) => j.job_id !== jobId));
    } catch { /* ignore */ }
  };

  const updateJobInList = (jobId: string, data: Record<string, unknown>) => {
    setPipelineJobs((prev) =>
      prev.map((j) =>
        j.job_id === jobId
          ? {
              ...j,
              status: (data.status as PipelineJob['status']) ?? (data.status_code as PipelineJob['status']) ?? j.status,
              status_code: (data.status_code as string) ?? j.status_code,
              stage: (data.stage as string) ?? j.stage,
              stage_code: (data.stage_code as string) ?? j.stage_code,
              stage_label: (data.stage_label as string) ?? j.stage_label,
              progress: (data.progress as number) ?? j.progress,
              error_code: (data.error_code as string) ?? j.error_code,
              error_detail: (data.error_detail as string) ?? j.error_detail,
              can_cancel: (data.can_cancel as boolean) ?? j.can_cancel,
              can_retry: (data.can_retry as boolean) ?? j.can_retry,
            }
          : j,
      ),
    );
  };

  const submitJob = async () => {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const job = await api.pipeline.submitJob(uploadFile, activeLibraryId);
      setUploadFile(null);
      await fetchJobs();
      if (job.job_id) {
        streamJobEvents(job.job_id);
      }
    } catch { /* ignore */ }
    finally { setUploading(false); }
  };

  const streamJobEvents = (jobId: string, jobLibraryId?: string) => {
    if (sseRef.current) sseRef.current.close();

    const refreshList = () => { fetchJobs(); };
    const es = api.pipeline.streamJobEvents(jobId);

    es.addEventListener('accepted', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); } catch {/* */}
      appendLog('info', `Job accepted: ${jobId}`);
    });
    es.addEventListener('stage_started', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); appendLog('event', `Stage started: ${p.stage || p.stage_code || ''}`); } catch { appendLog('event', 'Stage started'); }
    });
    es.addEventListener('stage_progress', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); appendLog('data', `Progress: ${p.progress ?? 0}%`); } catch { appendLog('data', 'Progress update'); }
    });
    es.addEventListener('stage_done', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); appendLog('info', `Stage done: ${p.stage || ''}`); } catch { appendLog('info', 'Stage done'); }
    });
    es.addEventListener('completed', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); } catch {/* */}
      appendLog('info', `Job ${jobId} completed`);
      window.dispatchEvent(new CustomEvent('pipeline-completed', { detail: { libraryId: jobLibraryId || activeLibraryId } }));
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      refreshList();
    });
    es.addEventListener('failed', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); appendLog('warn', `Job failed: ${p.error || 'unknown'}`); } catch { appendLog('warn', 'Job failed'); }
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      refreshList();
    });
    es.addEventListener('cancelled', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); updateJobInList(jobId, p); } catch {/* */}
      appendLog('info', `Job ${jobId} cancelled`);
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      refreshList();
    });
    es.onerror = () => {
      es.close();
      sseRef.current = null;
      setSseConnected(false);
    };

    sseRef.current = es;
    setSseConnected(true);
  };

  const appendLog = (type: string, msg: string) => {
    const now = new Date();
    const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    setSseLog(prev => [...prev.slice(-50), { time, type, msg }]);
  };

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [sseLog]);

  const cancelJob = async (jobId: string) => {
    try { await api.pipeline.cancelJob(jobId); fetchJobs(); } catch { /* ignore */ }
  };

  const retryJob = async (jobId: string) => {
    try {
      const res = await api.pipeline.retryJob(jobId);
      const newJobId = (res as Record<string, unknown>)?.new_job as Record<string, unknown> | undefined;
      if (newJobId?.job_id) {
        streamJobEvents(String(newJobId.job_id));
      }
      fetchJobs();
    } catch { /* ignore */ }
  };

  const visibleJobs = useMemo(() => pipelineJobs, [pipelineJobs]);
  const selectedJobs = useMemo(
    () => visibleJobs.filter((j) => selectedJobIds.has(j.job_id)),
    [visibleJobs, selectedJobIds],
  );
  const allVisibleSelected = visibleJobs.length > 0 && visibleJobs.every((j) => selectedJobIds.has(j.job_id));

  const toggleSelectAllVisible = () => {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        visibleJobs.forEach((j) => next.delete(j.job_id));
      } else {
        visibleJobs.forEach((j) => next.add(j.job_id));
      }
      return next;
    });
  };

  const toggleSelectJob = (jobId: string, checked: boolean) => {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(jobId);
      else next.delete(jobId);
      return next;
    });
  };

  const batchOperate = async (action: 'cancel' | 'retry' | 'delete') => {
    if (!selectedJobs.length) return;
    const labelMap: Record<'cancel' | 'retry' | 'delete', string> = {
      cancel: '取消',
      retry: '重试',
      delete: '删除',
    };
    if (!confirm(`确认${labelMap[action]}已选中的 ${selectedJobs.length} 个任务？`)) return;
    try {
      const res = await api.pipeline.batchOperateJobs(action, selectedJobs.map((j) => j.job_id));
      if (action === 'retry') {
        const results = Array.isArray(res.results) ? res.results : [];
        for (const item of results) {
          if (item && typeof item === 'object' && item.retry_mode === 'recreate' && typeof item.job_id === 'string') {
            // no-op: backend recreate path does not return new job id here
          }
        }
      }
      const failed = Number(res.failure_count || 0);
      if (failed > 0) {
        window.alert(`批量${labelMap[action]}完成：成功 ${res.success_count}，失败 ${failed}`);
      }
      setSelectedJobIds(new Set());
      await fetchJobs();
    } catch (err) {
      window.alert(`批量${labelMap[action]}失败: ${String((err as Error)?.message || err)}`);
    }
  };

  const statusBadge = (status: string) => {
    const classes: Record<string, string> = {
      queued: 'bg-surface-container text-on-surface-variant animate-pulse',
      running: 'bg-secondary-container/20 text-secondary animate-pulse',
      completed: 'bg-secondary-container/20 text-secondary',
      failed: 'bg-error-container/20 text-error',
      cancelled: 'bg-surface-container text-outline',
    };
    return classes[status] || classes.queued;
  };

  return (
    <div className="flex-1 flex flex-col overflow-y-auto px-8 py-8 bg-surface-container-low/30 relative">
      <div className="flex justify-between items-end mb-8">
        <div className="space-y-1.5">
          <h2 className="text-3xl font-bold tracking-tight text-on-surface font-sans">文献导入</h2>
          <p className="text-sm text-on-surface-variant">导入论文并提取知识图谱</p>
        </div>
        <button onClick={refresh} disabled={refreshing} className="bg-secondary hover:bg-secondary/90 text-on-secondary flex items-center gap-2 px-5 py-2.5 rounded-xl shadow-lg shadow-secondary/20 transition-all active:scale-95 disabled:opacity-50">
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          <span className="font-bold text-sm">刷新</span>
        </button>
      </div>

      <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-visible glass-shadow mb-8">
        <div className="p-4 bg-surface-container-lowest border-b border-outline-variant flex items-center gap-3">
          <CloudUpload className="w-5 h-5 text-secondary" />
          <h3 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">上传文档</h3>
        </div>
        <div className="p-6 space-y-3">
          <div
            className="flex items-center gap-4 p-4 border-2 border-dashed border-outline-variant rounded-xl bg-surface-container-low/30 hover:border-secondary transition-all cursor-pointer"
            onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('border-secondary', 'bg-secondary-container/10'); }}
            onDragLeave={(e) => { e.currentTarget.classList.remove('border-secondary', 'bg-secondary-container/10'); }}
            onDrop={(e) => { e.currentTarget.classList.remove('border-secondary', 'bg-secondary-container/10'); }}
            onClick={() => document.getElementById('pdf-upload')?.click()}
          >
            <FileText className="w-8 h-8 text-outline shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-on-surface">
                {uploadFile ? uploadFile.name : '点击选择文件，或拖拽 PDF / DOCX / MD / HTML 到此窗口进行批量导入'}
              </p>
              <p className="text-xs text-outline font-mono mt-0.5">
                {uploadFile ? `${(uploadFile.size / 1024).toFixed(1)} KB` : '支持单文件选择或多文件拖拽'}
              </p>
            </div>
          </div>
          <p className="text-xs text-on-surface-variant text-center">
            建议单次拖拽不超过 10 个文件，超大批量导入可能造成卡顿
          </p>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <input
              type="file"
              accept=".pdf,.docx,.md,.html"
              onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              className="hidden"
              id="pdf-upload"
            />
            <button
              onClick={() => setShowZoteroModal(true)}
              className="shrink-0 flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-bold border-2 border-secondary text-secondary hover:bg-secondary-container/10 transition-all whitespace-nowrap"
            >
              <Database className="w-4 h-4" />
              从 Zotero 导入
            </button>
            <button
              onClick={submitJob}
              disabled={!uploadFile || uploading}
              className="shrink-0 bg-secondary text-on-secondary px-6 py-3 rounded-xl text-sm font-bold hover:opacity-90 transition-all shadow-lg shadow-secondary/10 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
            >
              {uploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-on-secondary border-t-transparent rounded-full animate-spin" />
                  上传中...
                </>
              ) : (
                <>
                  <CloudUpload className="w-4 h-4" />
                  导入选中文件
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <h3 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono flex-1">导入任务</h3>
        <span className="text-[13px] text-on-surface-variant font-mono">已选: {selectedJobs.length}</span>
        <button
          onClick={() => batchOperate('cancel')}
          disabled={selectedJobs.length === 0}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface disabled:opacity-50"
        >
          批量取消
        </button>
        <button
          onClick={() => batchOperate('retry')}
          disabled={selectedJobs.length === 0}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface disabled:opacity-50"
        >
          批量重试
        </button>
        <button
          onClick={() => batchOperate('delete')}
          disabled={selectedJobs.length === 0}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface disabled:opacity-50"
        >
          批量删除
        </button>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface outline-none"
        >
          {STATUS_OPTIONS.map((s) => <option key={s.value || 'all'} value={s.value}>{s.label}</option>)}
        </select>
        <select
          value={stageFilter}
          onChange={(e) => { setStageFilter(e.target.value); setPage(1); }}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface outline-none"
        >
          {STAGE_OPTIONS.map((s) => <option key={s.value || 'all'} value={s.value}>{s.label}</option>)}
        </select>
      </div>

      <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-hidden glass-shadow mb-8">
        <div className="max-h-[50vh] overflow-y-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-surface-container-low/10 text-xs font-mono font-black text-outline uppercase tracking-widest border-b border-outline-variant/10">
                <th className="px-4 py-4 w-[44px] text-center">
                  <input type="checkbox" checked={allVisibleSelected} onChange={() => toggleSelectAllVisible()} />
                </th>
                <th className="px-6 py-4 w-[130px]">任务ID</th>
                <th className="px-6 py-4">文件名</th>
                <th className="px-6 py-4 w-[140px]">阶段</th>
                <th className="px-6 py-4 w-[160px]">进度</th>
                <th className="px-6 py-4 text-center w-[120px]">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {visibleJobs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-on-surface-variant text-sm">
                    暂无导入任务
                  </td>
                </tr>
              )}
              {visibleJobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-surface-container-low/10 transition-colors group">
                  <td className="px-4 py-4 text-center">
                    <input
                      type="checkbox"
                      checked={selectedJobIds.has(job.job_id)}
                      onChange={(e) => toggleSelectJob(job.job_id, e.target.checked)}
                    />
                  </td>
                  <td className="px-6 py-4 font-mono text-[13px] font-bold text-on-surface-variant">{job.job_id?.slice(0, 12)}...</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center text-red-500 border border-red-100 group-hover:scale-110 transition-transform">
                        <FileText className="w-4 h-4" />
                      </div>
                      <span className="text-sm font-semibold text-on-surface break-all">{job.display_name || job.file_name || job.input_path?.split('/').pop() || '未知'}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 shrink-0">
                    <span className={`text-xs font-mono font-black uppercase px-2 py-0.5 rounded-full whitespace-nowrap ${statusBadge(job.status || '')}`}>
                      {job.stage_label || job.stage || '-'}
                    </span>
                  </td>
                  <td className="px-6 py-4 shrink-0" style={{ minWidth: 140 }}>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 bg-surface-container h-1.5 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-1000 ease-in-out ${job.status === 'completed' ? 'bg-secondary' : 'bg-secondary animate-pulse-soft'}`}
                          style={{ width: `${job.progress ?? (job.status === 'completed' ? 100 : 0)}%` }}
                        />
                      </div>
                      <span className="text-[13px] font-mono font-bold text-on-surface-variant">{job.progress ?? (job.status === 'completed' ? 100 : 0)}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <div className="flex justify-center gap-1.5">
                      <button onClick={() => deleteJob(job.job_id, job.file_name || '')} className="text-outline hover:text-red-500 hover:scale-110 transition-all p-1" title="删除"><Trash2 className="w-3.5 h-3.5" /></button>
                      <button onClick={() => setLogJob(job)} className="text-outline hover:text-secondary hover:scale-110 transition-all p-1" title="日志"><Terminal className="w-3.5 h-3.5" /></button>
                      {job.status === 'completed' && (
                        <button onClick={() => setSelectedJob(job)} className="text-outline hover:text-secondary hover:scale-110 transition-all p-1" title="详情"><Info className="w-3.5 h-3.5" /></button>
                      )}
                      {(job.status === 'queued' || job.status === 'running') && job.can_cancel && (
                        <button onClick={() => cancelJob(job.job_id)} className="text-outline hover:text-error hover:scale-110 transition-all p-1" title="取消"><XCircle className="w-3.5 h-3.5" /></button>
                      )}
                      {(job.status === 'failed' || job.status === 'cancelled') && job.can_retry && (
                        <button onClick={() => retryJob(job.job_id)} className="text-outline hover:text-secondary hover:scale-110 transition-all p-1" title="重试"><RefreshCw className="w-3.5 h-3.5" /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="flex items-center justify-between mb-8 text-xs text-on-surface-variant">
        <span>总任务 {totalJobs} 条 · 第 {page} / {totalPages} 页</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 disabled:opacity-50"
          >
            上一页
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      </div>

      {selectedJob && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setSelectedJob(null)}>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest font-mono mb-4">任务详情</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between"><span className="text-on-surface-variant">任务ID</span><span className="font-mono text-on-surface">{selectedJob.job_id}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">状态</span><span className="font-mono text-on-surface">{selectedJob.status}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">阶段</span><span className="font-mono text-on-surface">{selectedJob.stage_label || selectedJob.stage || '-'}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">文献库</span><span className="font-mono text-on-surface">{selectedJob.library_id}</span></div>
              {selectedJob.error_detail && <div className="bg-error-container/10 border border-error/20 rounded-lg p-3 text-sm text-error">{selectedJob.error_detail}</div>}
            </div>
            <button onClick={() => setSelectedJob(null)} className="mt-6 w-full py-2 bg-surface-container border border-outline-variant rounded-lg text-sm font-medium hover:bg-surface-container-high transition-all">关闭</button>
          </div>
        </div>
      )}

      {logJob && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setLogJob(null)}>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-6 max-w-4xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest font-mono">任务日志</h3>
              <button onClick={() => setLogJob(null)} className="px-3 py-1.5 bg-surface-container border border-outline-variant rounded text-xs">关闭</button>
            </div>
            <div className="text-xs font-mono text-on-surface-variant mb-4">
              <div>任务: {logJob.job_id}</div>
              <div>文件: {logJob.display_name || logJob.file_name || '-'}</div>
              <div>状态: {logJob.status} / 阶段: {logJob.stage_code || logJob.stage || '-'}</div>
              <div>事件流: {liveLogConnected ? '已连接' : '已断开'}</div>
            </div>
            <div className="space-y-2">
              {liveJobLogs.map((r, idx) => (
                <div key={`${r.time}-${idx}`} className="rounded border border-outline-variant bg-surface-container-low/30 overflow-hidden">
                  <button
                    onClick={() => setExpandedLogItems((prev) => ({ ...prev, [`${r.time}-${idx}`]: !prev[`${r.time}-${idx}`] }))}
                    className="w-full flex items-center gap-3 p-2 text-left hover:bg-surface-container-low transition-colors"
                  >
                    <span className="text-xs font-mono text-outline w-44 shrink-0">{r.time}</span>
                    <span className={`text-[13px] font-mono shrink-0 ${r.level === 'error' ? 'text-error' : r.level === 'warn' ? 'text-amber-600' : 'text-secondary'}`}>
                      [{r.level.toUpperCase()}]
                    </span>
                    <span className="text-sm text-on-surface break-all flex-1">{r.text}</span>
                    <ChevronDown className={`w-3.5 h-3.5 text-outline transition-transform ${expandedLogItems[`${r.time}-${idx}`] ? 'rotate-180' : ''}`} />
                  </button>
                  {expandedLogItems[`${r.time}-${idx}`] && (
                    <div className="px-3 pb-3">
                      <div className="text-xs text-on-surface-variant whitespace-pre-wrap break-all bg-surface-container p-2 rounded border border-outline-variant/40">
                        {r.detail || '（无详情）'}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      <ZoteroImportModal open={showZoteroModal} onClose={() => setShowZoteroModal(false)} onImportDone={fetchJobs} />
    </div>
  );
}

