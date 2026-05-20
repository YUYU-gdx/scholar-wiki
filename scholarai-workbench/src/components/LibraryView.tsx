import { FileText, ExternalLink, Library, Layers, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useApp } from '../app-context';
import { api } from '../api';
import type { GraphNode, LiteraturePaper } from '../types';
import { journalListTags } from '../data/journalLists';
import { hasTranslationBlocks } from './reader/TranslationMarkdown';

const MODE_KEY = 'kn_graph_library_mode';
const CUSTOM_PAPER_TAGS_STORAGE_KEY = 'library_custom_paper_tags_v1';

type Mode = 'papers' | 'variables';
type PaperFileAvailability = {
  pdf: boolean;
  markdown: boolean;
  html: boolean;
};
type PaperFileStatus = PaperFileAvailability & {
  loading: boolean;
};
type LibraryPaperRow = {
  scopedKey: string;
  paperId: string;
  rawPaperId: string;
  libraryId: string;
  title: string;
  metaLine: string;
  journal: string;
  sourceMdPath: string;
  files: PaperFileAvailability;
  variables: GraphNode[];
};
type PaperTranslationState = {
  jobId: string;
  progress: number;
  status: string;
  running: boolean;
};
type PersistedPaperTranslationJob = {
  scopedKey: string;
  libraryId: string;
  paperId: string;
  mdPath: string;
  jobId: string;
  progress: number;
  status: string;
  running: boolean;
};

const LIB_TRANSLATION_JOB_STORAGE_KEY = 'library_translation_jobs_v1';

function loadCustomPaperTags(): Record<string, string[]> {
  try {
    const raw = window.localStorage.getItem(CUSTOM_PAPER_TAGS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const tags = value.map((x) => String(x || '').trim()).filter(Boolean).slice(0, 12);
      if (tags.length) out[key] = Array.from(new Set(tags));
    }
    return out;
  } catch {
    return {};
  }
}

function saveCustomPaperTags(tags: Record<string, string[]>): void {
  try {
    window.localStorage.setItem(CUSTOM_PAPER_TAGS_STORAGE_KEY, JSON.stringify(tags));
  } catch {
    // ignore
  }
}

type SelectionState = {
  pivot: number;
  focused: number;
  selected: Set<number>;
};

function createSelection(): SelectionState {
  return { pivot: 0, focused: 0, selected: new Set() };
}

function firstTitle(v: Record<string, unknown>, paperId: string): string {
  const pretty = (s: string): string => String(s || '').replace(/\.pdf$/i, '').replace(/__/g, ' ').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  const display = String(v.display_title || '').trim();
  if (display) return pretty(display);
  const title = String(v.title || '').trim();
  if (title) return pretty(title);
  return pretty(paperId);
}

function metaLine(v: Record<string, unknown>): string {
  const authors = Array.isArray(v.authors_json)
    ? (v.authors_json as unknown[])
      .map((x) => {
        if (x && typeof x === 'object' && 'name' in (x as Record<string, unknown>)) {
          return String((x as Record<string, unknown>).name || '').trim();
        }
        if (typeof x === 'string') return x.trim();
        return '';
      })
      .filter(Boolean)
    : [];
  const authorText = authors.length ? authors.slice(0, 3).join('、') : '未知作者';
  const journal = String(v.journal || '').trim() || '未知期刊';
  const date = String(v.publication_date || '').trim() || (v.publication_year ? String(v.publication_year) : '未知时间');
  return `${authorText} | ${journal} | ${date}`;
}

export default function LibraryView() {
  const {
    graphData,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedNodeId,
    setSelectedNodeLibraryId,
    setSelectedPaperRawId,
    setReaderReturnView,
    setCurrentView,
    selectedLibraryIds,
  } = useApp();
  const [expandedPapers, setExpandedPapers] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<Mode>(() => (localStorage.getItem(MODE_KEY) as Mode) || 'papers');
  const [libraryPapers, setLibraryPapers] = useState<LiteraturePaper[]>([]);
  const [papersLoading, setPapersLoading] = useState(false);
  const [paperTranslations, setPaperTranslations] = useState<Record<string, PaperTranslationState>>({});
  const [translatedPaperFlags, setTranslatedPaperFlags] = useState<Record<string, boolean>>({});
  const [customPaperTags, setCustomPaperTags] = useState<Record<string, string[]>>(() => loadCustomPaperTags());
  const pollingJobsRef = useRef<Set<string>>(new Set());

  const persistPaperTranslationJobs = useCallback((jobs: PersistedPaperTranslationJob[]) => {
    try {
      window.sessionStorage.setItem(LIB_TRANSLATION_JOB_STORAGE_KEY, JSON.stringify(jobs));
    } catch {
      // ignore
    }
  }, []);

  const loadPersistedPaperTranslationJobs = useCallback((): PersistedPaperTranslationJob[] => {
    try {
      const raw = window.sessionStorage.getItem(LIB_TRANSLATION_JOB_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .map((x) => (x && typeof x === 'object' ? x as PersistedPaperTranslationJob : null))
        .filter((x): x is PersistedPaperTranslationJob => !!x && !!x.scopedKey && !!x.jobId);
    } catch {
      return [];
    }
  }, []);

  const upsertPersistedPaperTranslationJob = useCallback((entry: PersistedPaperTranslationJob) => {
    const current = loadPersistedPaperTranslationJobs();
    const next = current.filter((x) => x.scopedKey !== entry.scopedKey);
    next.push(entry);
    persistPaperTranslationJobs(next);
  }, [loadPersistedPaperTranslationJobs, persistPaperTranslationJobs]);

  const addCustomTagToPapers = useCallback((papers: LibraryPaperRow[]) => {
    const raw = window.prompt('输入要添加的标签');
    const tag = String(raw || '').trim();
    if (!tag) return;
    setCustomPaperTags((prev) => {
      const next: Record<string, string[]> = { ...prev };
      for (const p of papers) {
        const current = next[p.scopedKey] || [];
        next[p.scopedKey] = Array.from(new Set([...current, tag])).slice(0, 12);
      }
      saveCustomPaperTags(next);
      return next;
    });
  }, []);

  const clearCustomTagsForPapers = useCallback((papers: LibraryPaperRow[]) => {
    setCustomPaperTags((prev) => {
      const next: Record<string, string[]> = { ...prev };
      for (const p of papers) {
        delete next[p.scopedKey];
      }
      saveCustomPaperTags(next);
      return next;
    });
  }, []);

  const selRef = useRef<SelectionState>(createSelection());
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; visible: boolean } | null>(null);
  const [, forceUpdate] = useReducer((x: number) => x + 1, 0);

  const selectedKey = useMemo(() => selectedLibraryIds.slice().sort().join('|'), [selectedLibraryIds]);

  const refreshLibraryPapers = useCallback(() => {
    const libIds = selectedLibraryIds.map((x) => String(x || '').trim()).filter(Boolean);
    if (!libIds.length) {
      setLibraryPapers([]);
      return;
    }
    setPapersLoading(true);
    Promise.all(libIds.map((libId) => api.literature.listLibraryPapers(libId)))
      .then((payloads) => setLibraryPapers(payloads.flatMap((p) => p.papers || [])))
      .catch(() => setLibraryPapers([]))
      .finally(() => setPapersLoading(false));
  }, [selectedKey]);

  useEffect(() => {
    refreshLibraryPapers();
  }, [refreshLibraryPapers]);

  useEffect(() => {
    const handler = () => refreshLibraryPapers();
    window.addEventListener('paper-deleted', handler as EventListener);
    window.addEventListener('pipeline-completed', handler as EventListener);
    return () => {
      window.removeEventListener('paper-deleted', handler as EventListener);
      window.removeEventListener('pipeline-completed', handler as EventListener);
    };
  }, [refreshLibraryPapers]);

  const deletePaper = async (p: { paperId: string; libraryId: string; scopedKey: string }) => {
    if (!confirm(`确定删除「${p.paperId}」吗？\n将同时删除数据库记录和磁盘文件。`)) return;
    try {
      await api.graph.deletePaper(p.paperId, p.libraryId);
      setLibraryPapers((prev) => prev.filter((row) => `${row.library_id}::${row.paper_id}` !== p.scopedKey));
      window.dispatchEvent(new CustomEvent('paper-deleted', { detail: { libraryId: p.libraryId } }));
    } catch { /* ignore */ }
  };

  const variables = useMemo(() => (graphData?.nodes || []).filter((n) => String(n.type || '') === 'variable'), [graphData]);

  const paperList = useMemo(() => {
    const selected = new Set((selectedLibraryIds || []).map((x) => String(x || '').trim()).filter(Boolean));
    const out: LibraryPaperRow[] = [];
    const seen = new Set<string>();

    for (const row of libraryPapers) {
      const d = (row || {}) as LiteraturePaper;
      const libraryId = String(d.library_id || '').trim();
      if (selected.size > 0 && !selected.has(libraryId)) continue;

      const paperId = String(d.paper_id || '').trim();
      if (!paperId) continue;

      const dedupeKey = `${libraryId}::${paperId}`;
      if (seen.has(dedupeKey)) continue;
      seen.add(dedupeKey);

      const paperVars = variables.filter((v) => {
        const src = String(v.latest_concept_source?.paper_id || '');
        const dom = String(v.dominant_paper_id || '');
        return src === paperId || dom === paperId;
      });

      out.push({
        scopedKey: dedupeKey,
        paperId,
        rawPaperId: String(d.raw_paper_id || paperId),
        libraryId,
        title: firstTitle(d as unknown as Record<string, unknown>, paperId),
        metaLine: metaLine(d as unknown as Record<string, unknown>),
        journal: String(d.journal || '').trim(),
        sourceMdPath: String(d.source_md_path || '').trim(),
        files: {
          pdf: !!d.files?.pdf,
          markdown: !!d.files?.markdown,
          html: !!d.files?.html,
        },
        variables: paperVars,
      });
    }

    return out.sort((a, b) => {
      const libCmp = a.libraryId.localeCompare(b.libraryId);
      if (libCmp !== 0) return libCmp;
      return a.paperId.localeCompare(b.paperId);
    });
  }, [libraryPapers, variables, selectedLibraryIds]);

  const paperFilesByScopedKey = useMemo<Record<string, PaperFileStatus>>(() => {
    const next: Record<string, PaperFileStatus> = {};
    for (const p of paperList) {
      next[p.scopedKey] = { ...p.files, loading: false };
    }
    return next;
  }, [paperList]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const shell = window.desktopShell;
      if (!shell || shell.runtime !== 'electron') {
        if (!cancelled) setTranslatedPaperFlags({});
        return;
      }
      const entries = await Promise.all(paperList.map(async (p) => {
        const mdPath = String(p.sourceMdPath || '').trim();
        if (!mdPath || !p.files.markdown) return [p.scopedKey, false] as const;
        try {
          const read = await shell.readLocalText(mdPath);
          const raw = String(read?.data || '');
          return [p.scopedKey, hasTranslationBlocks(raw)] as const;
        } catch {
          return [p.scopedKey, false] as const;
        }
      }));
      if (cancelled) return;
      const next: Record<string, boolean> = {};
      for (const [key, flag] of entries) next[key] = !!flag;
      setTranslatedPaperFlags(next);
    };
    run();
    return () => { cancelled = true; };
  }, [paperList]);

  // 鈹€鈹€ Selection logic 鈹€鈹€

  const isSelected = useCallback((index: number) => {
    return selRef.current.selected.has(index);
  }, []);

  const select = useCallback((index: number) => {
    const s = selRef.current;
    s.selected.clear();
    s.selected.add(index);
    s.pivot = index;
    s.focused = index;
    forceUpdate();
  }, []);

  const toggleSelect = useCallback((index: number) => {
    const s = selRef.current;
    if (s.selected.has(index)) {
      s.selected.delete(index);
    } else {
      s.selected.add(index);
    }
    s.pivot = index;
    s.focused = index;
    forceUpdate();
  }, []);

  const shiftSelect = useCallback((index: number) => {
    const s = selRef.current;
    s.selected.clear();
    const from = Math.min(index, s.pivot);
    const to = Math.max(index, s.pivot);
    for (let i = from; i <= to; i++) {
      s.selected.add(i);
    }
    s.focused = index;
    forceUpdate();
  }, []);

  const selectAll = useCallback(() => {
    const s = selRef.current;
    s.selected.clear();
    for (let i = 0; i < paperList.length; i++) {
      s.selected.add(i);
    }
    forceUpdate();
  }, [paperList]);

  const clearSelection = useCallback(() => {
    const s = selRef.current;
    s.selected.clear();
    forceUpdate();
  }, []);

  const getSelectedPapers = useCallback(() => {
    return Array.from(selRef.current.selected).map((i) => paperList[i]).filter(Boolean);
  }, [paperList]);

  // 鈹€鈹€ Existing helpers 鈹€鈹€

  const setSelectedPaper = (paperId: string, libraryId: string) => {
    setSelectedPaperId(paperId);
    setSelectedPaperLibraryId(libraryId);
  };

  const openInReader = (paperId: string, libraryId: string, rawPaperId: string, preferredType: 'pdf' | 'markdown' | 'html' | null) => {
    setSelectedPaper(paperId, libraryId);
    setSelectedPaperRawId(rawPaperId || null);
    setSelectedPaperPreferredType(preferredType);
    setReaderReturnView('library');
    setCurrentView('reader');
  };

  const pollPaperTranslationJob = useCallback(async (scopedKey: string, mdPath: string, jobId: string) => {
    if (pollingJobsRef.current.has(jobId)) return;
    pollingJobsRef.current.add(jobId);
    const startedAt = Date.now();
    try {
      while (true) {
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
        const row = await api.chat.getTranslateJob(jobId);
        const status = String(row.status || 'queued');
        const progress = Math.max(0, Math.min(100, Number(row.progress || 0)));
        const running = status === 'queued' || status === 'running';
        setPaperTranslations((prev) => ({
          ...prev,
          [scopedKey]: { jobId, progress, status, running },
        }));
        const base = scopedKey.split('::');
        upsertPersistedPaperTranslationJob({
          scopedKey,
          libraryId: base[0] || '',
          paperId: base[1] || '',
          mdPath,
          jobId,
          progress,
          status,
          running,
        });
        if (status === 'completed') {
          const translated = String(row.result?.formatted_text || row.result?.translated_text || '').trim();
          if (!translated) throw new Error('translation_result_empty');
          if (window.desktopShell?.runtime === 'electron') {
            await window.desktopShell.writeLocalText(mdPath, translated);
          }
          setTranslatedPaperFlags((prev) => ({ ...prev, [scopedKey]: true }));
          setPaperTranslations((prev) => ({
            ...prev,
            [scopedKey]: { jobId, progress: 100, status: 'completed', running: false },
          }));
          return;
        }
        if (status === 'failed') {
          throw new Error(String(row.error || 'translation_job_failed'));
        }
        if (Date.now() - startedAt > 4 * 60 * 60 * 1000) {
          throw new Error('translation_job_timeout');
        }
      }
    } finally {
      pollingJobsRef.current.delete(jobId);
    }
  }, [upsertPersistedPaperTranslationJob]);

  const handleTranslatePaper = useCallback(async (p: LibraryPaperRow) => {
    const mdPath = String(p.sourceMdPath || '').trim();
    if (!mdPath || window.desktopShell?.runtime !== 'electron') {
      window.alert('当前环境不支持直接写回 MD 文件');
      return;
    }
    const existing = paperTranslations[p.scopedKey];
    if (existing?.running) return;
    if (translatedPaperFlags[p.scopedKey]) {
      window.alert('该论文已存在译文块，已跳过。');
      return;
    }
    try {
      setPaperTranslations((prev) => ({
        ...prev,
        [p.scopedKey]: { jobId: '', progress: 0, status: 'submitting', running: true },
      }));
      const read = await window.desktopShell.readLocalText(mdPath);
      if (!read?.ok) throw new Error(String(read?.error || 'read_markdown_failed'));
      const markdown = String(read.data || '').trim();
      if (!markdown) throw new Error('markdown_empty');
      const cfg = await api.chat.getTranslationProviderConfig();
      const submit = await api.chat.submitTranslateJob(markdown, cfg, `library:${p.libraryId}`, true);
      const jobId = String(submit.job_id || '').trim();
      if (!jobId) throw new Error('translation_job_id_missing');
      setPaperTranslations((prev) => ({
        ...prev,
        [p.scopedKey]: { jobId, progress: 0, status: 'queued', running: true },
      }));
      upsertPersistedPaperTranslationJob({
        scopedKey: p.scopedKey,
        libraryId: p.libraryId,
        paperId: p.paperId,
        mdPath,
        jobId,
        progress: 0,
        status: 'queued',
        running: true,
      });
      await pollPaperTranslationJob(p.scopedKey, mdPath, jobId);
      window.dispatchEvent(new CustomEvent('paper-translation-completed', { detail: { libraryId: p.libraryId, paperId: p.paperId } }));
    } catch (e) {
      const msg = String((e as Error).message || 'unknown_error');
      setPaperTranslations((prev) => ({
        ...prev,
        [p.scopedKey]: { jobId: prev[p.scopedKey]?.jobId || '', progress: prev[p.scopedKey]?.progress || 0, status: `failed:${msg}`, running: false },
      }));
      window.alert(`全文对照翻译失败：${msg}`);
    }
  }, [paperTranslations, pollPaperTranslationJob, translatedPaperFlags, upsertPersistedPaperTranslationJob]);

  useEffect(() => {
    const persisted = loadPersistedPaperTranslationJobs();
    if (!persisted.length) return;
    const next: Record<string, PaperTranslationState> = {};
    for (const row of persisted) {
      next[row.scopedKey] = {
        jobId: row.jobId,
        progress: Math.max(0, Math.min(100, Number(row.progress || 0))),
        status: String(row.status || 'queued'),
        running: !!row.running,
      };
    }
    setPaperTranslations((prev) => ({ ...next, ...prev }));
  }, [loadPersistedPaperTranslationJobs]);

  useEffect(() => {
    if (!paperList.length) return;
    const scopedMap = new Map(paperList.map((p) => [p.scopedKey, p]));
    const persisted = loadPersistedPaperTranslationJobs();
    for (const row of persisted) {
      if (!row.running) continue;
      const paper = scopedMap.get(row.scopedKey);
      if (!paper) continue;
      const mdPath = String(row.mdPath || paper.sourceMdPath || '').trim();
      if (!mdPath || !row.jobId) continue;
      void pollPaperTranslationJob(row.scopedKey, mdPath, row.jobId);
    }
  }, [paperList, loadPersistedPaperTranslationJobs, pollPaperTranslationJob]);

  const variableRows = useMemo(() => {
    const paperTitleById = new Map<string, string>();
    for (const p of paperList) {
      const pid = String(p.paperId || '').trim();
      const ptitle = String(p.title || '').trim();
      if (pid && ptitle && !paperTitleById.has(pid)) paperTitleById.set(pid, ptitle);
    }
    return variables.map((v) => ({
      id: v.id,
      libraryId: String(v.library_id || ''),
      name: v.label || v.name || v.id,
      concept: String(v.latest_concept || '').trim() || '暂无概念定义',
      sourcePaperId: String(v.latest_concept_source?.paper_id || v.dominant_paper_id || '-'),
      sourcePaperTitle: String(
        paperTitleById.get(String(v.latest_concept_source?.paper_id || v.dominant_paper_id || '').trim()) || '',
      ).trim(),
    })).sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
  }, [variables, paperList]);

  const openVariableSourceInReader = (row: { id: string; libraryId: string; sourcePaperId: string }) => {
    const sourcePaperId = String(row.sourcePaperId || '').trim();
    const hit = paperList.find((p) => (
      p.libraryId === row.libraryId && (
        p.paperId === sourcePaperId ||
        p.rawPaperId === sourcePaperId ||
        sourcePaperId === p.scopedKey.split('::').at(-1)
      )
    ));
    if (hit) {
      openInReader(hit.paperId, hit.libraryId, hit.rawPaperId, null);
      return;
    }
    setSelectedNodeId(row.id);
    setSelectedNodeLibraryId(row.libraryId);
    if (sourcePaperId && sourcePaperId !== '-') {
      setSelectedPaperId(sourcePaperId);
      setSelectedPaperLibraryId(row.libraryId);
      setSelectedPaperRawId(sourcePaperId);
      setSelectedPaperPreferredType(null);
    }
    setReaderReturnView('library');
    setCurrentView('reader');
  };

  const setLibraryMode = (next: Mode) => {
    setMode(next);
    localStorage.setItem(MODE_KEY, next);
  };

  return (
    <div className="flex-1 overflow-auto px-8 py-6 space-y-6">
      <div className="flex items-center gap-3">
        <Library className="w-5 h-5 text-secondary" />
        <h2 className="text-2xl font-medium tracking-tight text-on-surface">文献库</h2>
        <span className="text-xs font-mono font-bold text-outline-variant bg-surface-container px-2 py-0.5 rounded">已选: {selectedLibraryIds.join(', ')}</span>
      </div>

      <div className="flex items-center gap-2 p-1 bg-surface-container-low w-fit rounded-xl border border-outline-variant">
        <button onClick={() => setLibraryMode('papers')} className={`px-4 py-1.5 text-xs font-bold rounded-lg ${mode === 'papers' ? 'bg-surface-container-lowest text-on-surface' : 'text-outline'}`}>论文</button>
        <button onClick={() => setLibraryMode('variables')} className={`px-4 py-1.5 text-xs font-bold rounded-lg ${mode === 'variables' ? 'bg-surface-container-lowest text-on-surface' : 'text-outline'}`}>变量</button>
      </div>

      {mode === 'papers' && (
        <section
          className="space-y-3"
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
              e.preventDefault();
              selectAll();
            }
            if (e.key === 'Escape') {
              clearSelection();
              setCtxMenu(null);
            }
          }}
          tabIndex={-1}
        >
          {papersLoading && paperList.length === 0 && (
            <div className="text-sm text-on-surface-variant text-center py-8">
              正在加载文献...
            </div>
          )}
          {!papersLoading && paperList.length === 0 && (
            <div className="text-sm text-on-surface-variant text-center py-8">
              暂未导入文献
            </div>
          )}
          {paperList.map((p, idx) => {
            const expanded = !!expandedPapers[p.scopedKey];
            const previewVars = p.variables.slice(0, 5);
            const remain = Math.max(0, p.variables.length - 5);
            const detected = paperFilesByScopedKey[p.scopedKey];
            const hasPdf = !!detected?.pdf;
            const hasMd = !!detected?.markdown;
            const loadingFiles = !detected || !!detected.loading;
            const tr = paperTranslations[p.scopedKey];
            const translated = !!translatedPaperFlags[p.scopedKey];
            const automaticTags = journalListTags(p.journal);
            const userTags = customPaperTags[p.scopedKey] || [];
            return (
              <div
                key={p.scopedKey}
                className={`p-4 bg-surface-container-lowest border border-outline-variant rounded-xl ${isSelected(idx) ? 'ring-2 ring-secondary' : ''}`}
                onClick={(e) => {
                  if (e.shiftKey) shiftSelect(idx);
                  else if (e.ctrlKey || e.metaKey) toggleSelect(idx);
                  else select(idx);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  if (!isSelected(idx)) select(idx);
                  setCtxMenu({ x: e.clientX, y: e.clientY, visible: true });
                }}
              >
                <div className="flex items-center justify-between gap-3">
                  <button onClick={(e) => (e.stopPropagation(), setExpandedPapers((prev) => ({ ...prev, [p.scopedKey]: !prev[p.scopedKey] })))} className="flex items-center gap-2 text-left">
                    {expanded ? <ChevronDown className="w-4 h-4 text-outline" /> : <ChevronRight className="w-4 h-4 text-outline" />}
                      <div>
                        <div className="text-sm font-semibold text-on-surface">{p.title}</div>
                      <div className="text-xs text-on-surface-variant">{p.metaLine}</div>
                      {(translated || automaticTags.length > 0 || userTags.length > 0) && (
                        <div className="mt-1 flex flex-wrap items-center gap-1">
                          {translated && (
                            <span className="inline-flex items-center rounded-md border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">
                              已翻译
                            </span>
                          )}
                          {automaticTags.map((tag) => (
                            <span key={`${p.scopedKey}-${tag}`} className="inline-flex items-center rounded-md border border-sky-300 bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-700">
                              {tag}
                            </span>
                          ))}
                          {userTags.map((tag) => (
                            <span key={`${p.scopedKey}-custom-${tag}`} className="inline-flex items-center rounded-md border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                      </div>
                  </button>
                  {loadingFiles ? (
                    <div className="w-6 h-6 rounded-full border border-outline-variant bg-surface-container flex items-center justify-center" title="加载中">
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-secondary" />
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      {hasPdf && <button onClick={(e) => (e.stopPropagation(), openInReader(p.paperId, p.libraryId, p.rawPaperId, 'pdf'))} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />PDF</button>}
                      {hasMd && <button onClick={(e) => (e.stopPropagation(), openInReader(p.paperId, p.libraryId, p.rawPaperId, 'markdown'))} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary flex items-center gap-1"><ExternalLink className="w-3 h-3" />MD</button>}
                      {hasMd && (
                        <button
                          onClick={(e) => (e.stopPropagation(), void handleTranslatePaper(p))}
                          disabled={!!tr?.running}
                          className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary disabled:opacity-50"
                          title="全文对照翻译"
                        >
                          全文对照翻译
                        </button>
                      )}
                      <button onClick={(e) => (e.stopPropagation(), deletePaper(p))} className="text-xs px-2 py-1 rounded border border-red-200 hover:border-red-400 hover:bg-red-50 text-red-600 flex items-center gap-1">删除</button>
                    </div>
                  )}
                </div>
                <div className="mt-2 text-xs text-on-surface-variant">变量: {previewVars.map((v) => v.label || v.name || v.id).join('、') || '无'}{remain > 0 && `（+${remain} 个已折叠）`}</div>
                {!!tr && tr.status !== 'completed' && (
                  <div className="mt-2 text-xs text-on-surface-variant">
                    翻译任务: {tr.status} {tr.progress}%
                  </div>
                )}
                {expanded && (
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                    {p.variables.map((v) => (
                      <button key={`${p.scopedKey}-${v.id}`} onClick={(e) => (e.stopPropagation(), setSelectedNodeId(v.id), setSelectedNodeLibraryId(String(v.library_id || p.libraryId)), setCurrentView('graph'))} className="text-left p-2 bg-surface-container border border-outline-variant rounded-lg hover:border-secondary">
                        <div className="text-xs font-semibold text-on-surface truncate">{v.label || v.name || v.id}</div>
                        <div className="text-[13px] text-on-surface-variant truncate">{String(v.latest_concept || '').slice(0, 60) || '暂无概念'}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}

      {mode === 'papers' && ctxMenu?.visible && (() => {
        const papers = Array.from(selRef.current.selected).map((i) => paperList[i]).filter(Boolean);
        const hasPdf = papers.some((p) => paperFilesByScopedKey[p.scopedKey]?.pdf);
        const hasMd = papers.some((p) => paperFilesByScopedKey[p.scopedKey]?.markdown);
        const allExpanded = papers.every((p) => expandedPapers[p.scopedKey]);
        const hasCustomTags = papers.some((p) => (customPaperTags[p.scopedKey] || []).length > 0);
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setCtxMenu(null)} />
            <div
              className="fixed z-50 bg-surface-container-lowest border border-outline-variant rounded-xl shadow-lg py-1 min-w-[180px]"
              style={{ left: ctxMenu.x, top: ctxMenu.y }}
            >
              {hasPdf && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    const first = papers.find((p) => paperFilesByScopedKey[p.scopedKey]?.pdf);
                    if (first) openInReader(first.paperId, first.libraryId, first.rawPaperId, 'pdf');
                    setCtxMenu(null);
                  }}
                >
                  在阅读器中打开 (PDF)
                </button>
              )}
              {hasMd && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    const first = papers.find((p) => paperFilesByScopedKey[p.scopedKey]?.markdown);
                    if (first) openInReader(first.paperId, first.libraryId, first.rawPaperId, 'markdown');
                    setCtxMenu(null);
                  }}
                >
                  在阅读器中打开 (MD)
                </button>
              )}
              {hasMd && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    const targets = papers.filter((p) => paperFilesByScopedKey[p.scopedKey]?.markdown && !translatedPaperFlags[p.scopedKey]);
                    const skipped = papers.filter((p) => paperFilesByScopedKey[p.scopedKey]?.markdown && translatedPaperFlags[p.scopedKey]).length;
                    for (const p of targets) {
                      void handleTranslatePaper(p);
                    }
                    if (skipped > 0) {
                      window.alert(`已跳过 ${skipped} 篇已翻译论文。`);
                    }
                    setCtxMenu(null);
                  }}
                >
                  全文对照翻译 (MD) ({papers.filter((p) => paperFilesByScopedKey[p.scopedKey]?.markdown && !translatedPaperFlags[p.scopedKey]).length} 篇)
                </button>
              )}
              <button
                className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                onClick={() => {
                  const toExpand = !allExpanded;
                  setExpandedPapers((prev) => {
                    const next = { ...prev };
                    for (const p of papers) {
                      next[p.scopedKey] = toExpand;
                    }
                    return next;
                  });
                  setCtxMenu(null);
                }}
              >
                {allExpanded ? '折叠' : '展开'} ({papers.length} 篇)
              </button>
              <button
                className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                onClick={() => {
                  addCustomTagToPapers(papers);
                  setCtxMenu(null);
                }}
              >
                添加标签 ({papers.length} 篇)
              </button>
              {hasCustomTags && (
                <button
                  className="w-full text-left px-4 py-2 text-sm text-on-surface hover:bg-surface-container"
                  onClick={() => {
                    clearCustomTagsForPapers(papers);
                    setCtxMenu(null);
                  }}
                >
                  清空自定义标签
                </button>
              )}
              <div className="border-t border-outline-variant my-1" />
              <button
                className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                onClick={async () => {
                  const n = papers.length;
                  const names = papers.map((p) => p.paperId).join(', ');
                  if (!confirm(`确定删除 ${n} 篇论文吗？\n${names}\n将同时删除数据库记录和磁盘文件。`)) return;
                  let ok = 0;
                  let fail = 0;
                  await Promise.allSettled(papers.map((p) =>
                    api.graph.deletePaper(p.paperId, p.libraryId).then(() => { ok++; })
                  ));
                  fail = n - ok;
                  const deletedKeys = new Set(papers.map((p) => p.scopedKey));
                  setLibraryPapers((prev) => prev.filter((row) => !deletedKeys.has(`${row.library_id}::${row.paper_id}`)));
                  for (const p of papers) {
                    window.dispatchEvent(new CustomEvent('paper-deleted', { detail: { libraryId: p.libraryId } }));
                  }
                  clearSelection();
                  setCtxMenu(null);
                  if (fail > 0) alert(`已删除 ${ok} 篇${fail > 0 ? `，${fail} 篇失败` : ''}`);
                }}
              >
                删除 ({papers.length} 篇)
              </button>
            </div>
          </>
        );
      })()}

      {mode === 'variables' && (
        <section>
          <div className="flex items-center gap-3 mb-4">
            <Layers className="w-5 h-5 text-secondary" />
            <h3 className="text-xl font-medium text-on-surface">变量与概念</h3>
          </div>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead className="bg-surface-container-low border-b border-outline-variant"><tr><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">变量</th><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">概念</th><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">来源论文</th><th className="px-4 py-3" /></tr></thead>
              <tbody className="divide-y divide-outline-variant">
                {variableRows.map((row) => (
                  <tr key={`${row.libraryId}-${row.id}`} className="hover:bg-surface-container-low transition-colors">
                    <td className="px-4 py-3 text-sm text-on-surface font-medium">{row.name}</td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant">{row.concept}</td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant">{row.sourcePaperTitle || row.sourcePaperId}</td>
                    <td className="px-4 py-3 text-right"><button onClick={() => openVariableSourceInReader(row)} className="text-xs px-2 py-1 rounded border border-outline-variant hover:border-secondary">跳转</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}



