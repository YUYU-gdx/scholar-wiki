import { useState, useEffect, useRef, useCallback } from 'react';
import { CloudUpload, FileText, RefreshCw, CheckCircle, XCircle, Info, Terminal, Trash2 } from 'lucide-react';
import { useApp } from '../App';
import { api } from '../api';
import type { PipelineJob } from '../types';

export default function PipelineView() {
  const { activeLibraryId, pipelineJobs, setPipelineJobs } = useApp();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [sseLog, setSseLog] = useState<Array<{ time: string; type: string; msg: string }>>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const sseRef = useRef<EventSource | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const [selectedJob, setSelectedJob] = useState<PipelineJob | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await api.pipeline.listJobs(page, 25, statusFilter || undefined, activeLibraryId);
      setPipelineJobs(res.jobs || []);
    } catch { /* ignore */ }
  }, [page, statusFilter, activeLibraryId, setPipelineJobs]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);

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
    const es = api.pipeline.streamJobEvents(jobId);

    es.addEventListener('accepted', (evt) => {
      appendLog('info', `Job accepted: ${jobId}`);
    });
    es.addEventListener('stage_started', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); appendLog('event', `Stage started: ${p.stage || p.stage_code || ''}`); } catch { appendLog('event', 'Stage started'); }
    });
    es.addEventListener('stage_progress', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); appendLog('data', `Progress: ${p.progress ?? 0}%`); } catch { appendLog('data', 'Progress update'); }
    });
    es.addEventListener('stage_done', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); appendLog('info', `Stage done: ${p.stage || ''}`); } catch { appendLog('info', 'Stage done'); }
    });
    es.addEventListener('completed', () => {
      appendLog('info', `Job ${jobId} completed`);
      window.dispatchEvent(new CustomEvent('pipeline-completed', { detail: { libraryId: jobLibraryId || activeLibraryId } }));
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      fetchJobs();
    });
    es.addEventListener('failed', (evt) => {
      try { const p = JSON.parse(evt.data || '{}'); appendLog('warn', `Job failed: ${p.error || 'unknown'}`); } catch { appendLog('warn', 'Job failed'); }
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      fetchJobs();
    });
    es.addEventListener('cancelled', () => {
      appendLog('info', `Job ${jobId} cancelled`);
      es.close();
      sseRef.current = null;
      setSseConnected(false);
      fetchJobs();
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
          <h2 className="text-3xl font-bold tracking-tight text-on-surface font-sans">Data Pipeline</h2>
          <p className="text-sm text-on-surface-variant">Import papers and extract knowledge graphs</p>
        </div>
        <button onClick={refresh} disabled={refreshing} className="bg-secondary hover:bg-secondary/90 text-on-secondary flex items-center gap-2 px-5 py-2.5 rounded-xl shadow-lg shadow-secondary/20 transition-all active:scale-95 disabled:opacity-50">
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          <span className="font-bold text-sm">Refresh</span>
        </button>
      </div>

      <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-hidden glass-shadow mb-8">
        <div className="p-4 bg-surface-container-lowest border-b border-outline-variant flex items-center gap-3">
          <CloudUpload className="w-5 h-5 text-secondary" />
          <h3 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">Upload PDF</h3>
        </div>
        <div className="p-6">
          <div className="flex items-center gap-4">
            <label className="flex-1 min-w-0 relative">
              <input
                type="file"
                accept=".pdf"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="hidden"
                id="pdf-upload"
              />
              <label htmlFor="pdf-upload" className="flex items-center gap-3 p-4 border-2 border-dashed border-outline-variant rounded-xl cursor-pointer hover:border-secondary transition-all bg-surface-container-low/30">
                <FileText className="w-6 h-6 text-outline shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-on-surface truncate">{uploadFile ? uploadFile.name : 'Choose a PDF file'}</p>
                  <p className="text-[10px] text-outline font-mono">{uploadFile ? `${(uploadFile.size / 1024).toFixed(1)} KB` : 'Click to browse'}</p>
                </div>
              </label>
            </label>
            <button
              onClick={submitJob}
              disabled={!uploadFile || uploading}
              className="shrink-0 bg-secondary text-on-secondary px-6 py-4 rounded-xl text-sm font-bold hover:opacity-90 transition-all shadow-lg shadow-secondary/10 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
            >
              {uploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-on-secondary border-t-transparent rounded-full animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <CloudUpload className="w-4 h-4" />
                  Import
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <h3 className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono flex-1">Pipeline Jobs</h3>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-xs text-on-surface outline-none"
        >
          <option value="">All Status</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl overflow-hidden glass-shadow mb-8">
        <div className="overflow-x-auto max-h-[50vh] overflow-y-auto">
          <table className="w-full text-left border-collapse table-fixed">
            <thead>
              <tr className="bg-surface-container-low/10 text-[10px] font-mono font-black text-outline uppercase tracking-widest border-b border-outline-variant/10">
                <th className="px-6 py-4 w-[90px]">Job ID</th>
                <th className="px-6 py-4">Filename</th>
                <th className="px-6 py-4 w-[90px]">Stage</th>
                <th className="px-6 py-4 w-[150px]">Progress</th>
                <th className="px-6 py-4 text-center w-[50px]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {pipelineJobs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-on-surface-variant text-sm">
                    No pipeline jobs found.
                  </td>
                </tr>
              )}
              {pipelineJobs.map((job) => (
                <tr key={job.job_id} className="hover:bg-surface-container-low/10 transition-colors group">
                  <td className="px-6 py-4 font-mono text-[11px] font-bold text-on-surface-variant">{job.job_id?.slice(0, 12)}...</td>
                  <td className="px-6 py-4 min-w-0">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center text-red-500 border border-red-100 group-hover:scale-110 transition-transform">
                        <FileText className="w-4 h-4" />
                      </div>
                      <span className="text-sm font-semibold text-on-surface truncate">{job.display_name || job.input_path?.split('/').pop() || 'Unknown'}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 shrink-0">
                    <span className={`text-[10px] font-mono font-black uppercase px-2 py-0.5 rounded-full whitespace-nowrap ${statusBadge(job.status || '')}`}>
                      {job.stage_label || job.stage || job.status_code || '-'}
                    </span>
                  </td>
                  <td className="px-6 py-4 shrink-0" style={{minWidth: 140}}>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 bg-surface-container h-1.5 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-1000 ease-in-out ${job.status === 'completed' ? 'bg-secondary' : 'bg-secondary animate-pulse-soft'}`}
                          style={{ width: `${job.progress ?? (job.status === 'completed' ? 100 : 0)}%` }}
                        />
                      </div>
                      <span className="text-[11px] font-mono font-bold text-on-surface-variant">{job.progress ?? (job.status === 'completed' ? 100 : 0)}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-center">
                    <div className="flex justify-center gap-1.5">
                      <button onClick={() => deleteJob(job.job_id, job.file_name || '')} className="text-outline hover:text-red-500 hover:scale-110 transition-all p-1" title="删除"><Trash2 className="w-3.5 h-3.5" /></button>
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

      {selectedJob && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setSelectedJob(null)}>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest font-mono mb-4">Job Detail</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between"><span className="text-on-surface-variant">Job ID</span><span className="font-mono text-on-surface">{selectedJob.job_id}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">Status</span><span className="font-mono text-on-surface">{selectedJob.status}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">Stage</span><span className="font-mono text-on-surface">{selectedJob.stage_label || selectedJob.stage || '-'}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">Library</span><span className="font-mono text-on-surface">{selectedJob.library_id}</span></div>
              {selectedJob.error_detail && <div className="bg-error-container/10 border border-error/20 rounded-lg p-3 text-sm text-error">{selectedJob.error_detail}</div>}
            </div>
            <button onClick={() => setSelectedJob(null)} className="mt-6 w-full py-2 bg-surface-container border border-outline-variant rounded-lg text-sm font-medium hover:bg-surface-container-high transition-all">Close</button>
          </div>
        </div>
      )}
    </div>
  );
}