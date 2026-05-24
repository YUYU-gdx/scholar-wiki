import { FileText, ExternalLink, Library, Layers, ChevronDown, ChevronRight, Loader2, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useApp } from '../app-context';
import { api } from '../api';
import type { GraphNode, LiteraturePaper, LiteratureSearchHit, SemanticVariableMatch } from '../types';
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
type CustomTagDialogState = {
  visible: boolean;
  scopedKeys: string[];
  value: string;
};
type PaperContextMenuState = {
  x: number;
  y: number;
  visible: boolean;
  scopedKeys: string[];
};

const LIB_TRANSLATION_JOB_STORAGE_KEY = 'library_translation_jobs_v1';

function includesText(value: unknown, query: string): boolean {
  return String(value || '').toLowerCase().includes(query);
}

function hitPaperId(hit: LiteratureSearchHit): string {
  return String(hit.paper_id || hit.paperId || hit.id || '').trim();
}

function hitSnippet(hit: LiteratureSearchHit): string {
  return String(hit.sentence || hit.paragraph || hit.text || hit.content || '').replace(/\s+/g, ' ').trim();
}

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

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable;
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
  const [paperSearchQuery, setPaperSearchQuery] = useState('');
  const [paperFullTextLoading, setPaperFullTextLoading] = useState(false);
  const [paperFullTextError, setPaperFullTextError] = useState('');
  const [paperFullTextHits, setPaperFullTextHits] = useState<LiteratureSearchHit[]>([]);
  const [variableSearchQuery, setVariableSearchQuery] = useState('');
  const [variableSemanticLoading, setVariableSemanticLoading] = useState(false);
  const [variableSemanticError, setVariableSemanticError] = useState('');
  const [semanticVariableResults, setSemanticVariableResults] = useState<SemanticVariableMatch[]>([]);
  const [customTagDialog, setCustomTagDialog] = useState<CustomTagDialogState>({ visible: false, scopedKeys: [], value: '' });
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

  const openCustomTagDialog = useCallback((papers: LibraryPaperRow[]) => {
    const scopedKeys = papers.map((p) => p.scopedKey).filter(Boolean);
    if (!scopedKeys.length) return;
    setCustomTagDialog({ visible: true, scopedKeys, value: '' });
  }, []);

  const saveCustomTagDialog = useCallback(() => {
    const tag = String(customTagDialog.value || '').trim();
    if (!tag) return;
    setCustomPaperTags((prev) => {
      const next: Record<string, string[]> = { ...prev };
      for (const scopedKey of customTagDialog.scopedKeys) {
        const current = next[scopedKey] || [];
        next[scopedKey] = Array.from(new Set([...current, tag])).slice(0, 12);
      }
      saveCustomPaperTags(next);
      return next;
    });
    setCustomTagDialog({ visible: false, scopedKeys: [], value: '' });
  }, [customTagDialog]);

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
  const [ctxMenu, setCtxMenu] = useState<PaperContextMenuState | null>(null);
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

  const visiblePaperList = useMemo(() => {
    const q = paperSearchQuery.trim().toLowerCase();
    if (!q) return paperList;
    return paperList.filter((p) => {
      const automaticTags = journalListTags(p.journal);
      const userTags = customPaperTags[p.scopedKey] || [];
      return (
        includesText(p.title, q) ||
        includesText(p.metaLine, q) ||
        includesText(p.paperId, q) ||
        includesText(p.rawPaperId, q) ||
        includesText(p.journal, q) ||
        automaticTags.some((tag) => includesText(tag, q)) ||
        userTags.some((tag) => includesText(tag, q)) ||
        p.variables.some((v) => includesText(v.label || v.name || v.id, q) || includesText(v.latest_concept, q)) ||
        (q === 'translated' && !!translatedPaperFlags[p.scopedKey]) ||
        (q === 'pdf' && p.files.pdf) ||
        ((q === 'md' || q === 'markdown') && p.files.markdown)
      );
    });
  }, [customPaperTags, paperList, paperSearchQuery, translatedPaperFlags]);

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
    for (let i = 0; i < visiblePaperList.length; i++) {
      s.selected.add(i);
    }
    forceUpdate();
  }, [visiblePaperList]);

  const clearSelection = useCallback(() => {
    const s = selRef.current;
    s.selected.clear();
    forceUpdate();
  }, []);

  const getSelectedPapers = useCallback(() => {
    return Array.from(selRef.current.selected).map((i) => visiblePaperList[i]).filter(Boolean);
  }, [visiblePaperList]);

  const getPapersByScopedKeys = useCallback((scopedKeys: string[]) => {
    const wanted = new Set(scopedKeys);
    return paperList.filter((p) => wanted.has(p.scopedKey));
  }, [paperList]);

  useEffect(() => {
    if (mode !== 'papers') return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
        e.preventDefault();
        window.getSelection()?.removeAllRanges();
        selectAll();
        return;
      }
      if (e.key === 'Escape') {
        clearSelection();
        setCtxMenu(null);
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [clearSelection, mode, selectAll]);

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

  const visibleVariableRows = useMemo(() => {
    const q = variableSearchQuery.trim().toLowerCase();
    if (!q) return variableRows;
    return variableRows.filter((row) => (
      includesText(row.name, q) ||
      includesText(row.concept, q) ||
      includesText(row.sourcePaperId, q) ||
      includesText(row.sourcePaperTitle, q)
    ));
  }, [variableRows, variableSearchQuery]);

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

  const openPaperSearchHit = (hit: LiteratureSearchHit) => {
    const paperId = hitPaperId(hit);
    const libraryId = String(hit.library_id || hit.libraryId || '').trim();
    const paper = paperList.find((p) => (
      (!libraryId || p.libraryId === libraryId) &&
      (p.paperId === paperId || p.rawPaperId === paperId)
    ));
    const targetPaperId = paper?.paperId || paperId;
    const targetLibraryId = paper?.libraryId || libraryId || selectedLibraryIds[0] || '';
    if (!targetPaperId || !targetLibraryId) return;
    openInReader(targetPaperId, targetLibraryId, paper?.rawPaperId || targetPaperId, 'markdown');
    const snippet = hitSnippet(hit);
    if (snippet) {
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent('reader-search-and-jump', {
          detail: { paperId: targetPaperId, query: snippet },
        }));
      }, 350);
    }
  };

  const runPaperFullTextSearch = async () => {
    const q = paperSearchQuery.trim();
    if (!q) return;
    const libs = selectedLibraryIds.map((x) => String(x || '').trim()).filter(Boolean);
    if (!libs.length) return;
    setPaperFullTextLoading(true);
    setPaperFullTextError('');
    try {
      const results = await Promise.all(libs.map(async (libId) => {
        const res = await api.literature.search(q, libId, 20, 'sentence,paragraph', 0.4, 0.6);
        return (res.merged_hits || []).map((hit) => ({ ...hit, library_id: String(hit.library_id || libId) }));
      }));
      setPaperFullTextHits(results.flat());
    } catch (err) {
      setPaperFullTextError(String((err as Error)?.message || err));
      setPaperFullTextHits([]);
    } finally {
      setPaperFullTextLoading(false);
    }
  };

  const runVariableSemanticSearch = async () => {
    const q = variableSearchQuery.trim();
    if (!q) return;
    const libs = selectedLibraryIds.map((x) => String(x || '').trim()).filter(Boolean);
    if (!libs.length) return;
    setVariableSemanticLoading(true);
    setVariableSemanticError('');
    try {
      const res = await api.graph.semanticVariableSearch(q, 12, libs);
      setSemanticVariableResults(res.matched_variables || []);
    } catch (err) {
      setVariableSemanticError(String((err as Error)?.message || err));
      setSemanticVariableResults([]);
    } finally {
      setVariableSemanticLoading(false);
    }
  };

  const openSemanticVariableSource = (row: SemanticVariableMatch) => {
    const paperId = String(row.paper_id || '').trim();
    const libraryId = String(row.library_id || '').trim();
    const paper = paperList.find((p) => p.libraryId === libraryId && (p.paperId === paperId || p.rawPaperId === paperId));
    if (paper || (paperId && libraryId)) {
      openInReader(paper?.paperId || paperId, paper?.libraryId || libraryId, paper?.rawPaperId || paperId, 'markdown');
      const q = String(row.concept_text || row.variable_name || '').trim();
      if (q) {
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent('reader-search-and-jump', {
            detail: { paperId: paper?.paperId || paperId, query: q },
          }));
        }, 350);
      }
    }
  };

  const focusSemanticVariable = (row: SemanticVariableMatch) => {
    if (!row.node_id) return;
    setSelectedNodeId(row.node_id);
    setSelectedNodeLibraryId(String(row.library_id || ''));
    setCurrentView('graph');
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
          <div className="flex flex-col gap-3 rounded-xl border border-outline-variant bg-surface-container-lowest p-3">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-outline" />
                <input
                  value={paperSearchQuery}
                  onChange={(e) => setPaperSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void runPaperFullTextSearch();
                  }}
                  placeholder="搜索标题、作者、期刊、标签、变量；回车全文搜索"
                  className="w-full rounded-lg border border-outline-variant bg-surface-container py-2 pl-9 pr-3 text-sm outline-none focus:border-secondary"
                />
              </div>
              <button
                onClick={() => void runPaperFullTextSearch()}
                disabled={!paperSearchQuery.trim() || paperFullTextLoading}
                className="rounded-lg bg-secondary px-3 py-2 text-sm font-semibold text-on-secondary disabled:opacity-50"
              >
                {paperFullTextLoading ? '全文检索中...' : '全文检索'}
              </button>
            </div>
            <div className="text-xs text-on-surface-variant">
              本地匹配 {visiblePaperList.length}/{paperList.length} 篇
            </div>
            {!!paperFullTextError && (
              <div className="rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">{paperFullTextError}</div>
            )}
            {paperFullTextHits.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-mono uppercase text-outline">正文命中 {paperFullTextHits.length} 条</div>
                {paperFullTextHits.slice(0, 20).map((hit, i) => {
                  const pid = hitPaperId(hit);
                  const lib = String(hit.library_id || '').trim();
                  const snippet = hitSnippet(hit);
                  return (
                    <button
                      key={`${lib}-${pid}-${i}`}
                      onClick={() => openPaperSearchHit(hit)}
                      className="block w-full rounded-lg border border-outline-variant bg-surface-container p-3 text-left hover:border-secondary"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="truncate text-sm font-semibold text-on-surface">{String(hit.title || pid || '未命名文献')}</div>
                        <div className="shrink-0 text-[11px] font-mono text-outline">{lib}</div>
                      </div>
                      <div className="mt-1 line-clamp-2 text-xs text-on-surface-variant">{snippet || '无命中文本'}</div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {papersLoading && paperList.length === 0 && (
            <div className="text-sm text-on-surface-variant text-center py-8">
              正在加载文献...
            </div>
          )}
          {!papersLoading && visiblePaperList.length === 0 && (
            <div className="text-sm text-on-surface-variant text-center py-8">
              {paperList.length === 0 ? '暂未导入文献' : '没有匹配的文献'}
            </div>
          )}
          {visiblePaperList.map((p, idx) => {
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
                  let selectedIndexes: number[];
                  if (isSelected(idx)) {
                    selectedIndexes = Array.from(selRef.current.selected);
                  } else {
                    select(idx);
                    selectedIndexes = [idx];
                  }
                  const scopedKeys = selectedIndexes.map((i) => visiblePaperList[i]?.scopedKey).filter(Boolean);
                  setCtxMenu({ x: e.clientX, y: e.clientY, visible: true, scopedKeys });
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
                          翻译
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
        const papers = getPapersByScopedKeys(ctxMenu.scopedKeys);
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
                  翻译 (MD) ({papers.filter((p) => paperFilesByScopedKey[p.scopedKey]?.markdown && !translatedPaperFlags[p.scopedKey]).length} 篇)
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
                  setCtxMenu(null);
                  openCustomTagDialog(papers);
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

      {customTagDialog.visible && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 px-4" onClick={() => setCustomTagDialog({ visible: false, scopedKeys: [], value: '' })}>
          <form
            className="w-full max-w-md overflow-hidden rounded-2xl border border-outline-variant bg-surface-container-lowest shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              saveCustomTagDialog();
            }}
          >
            <div className="border-b border-outline-variant bg-surface-container-low px-5 py-4">
              <div className="text-sm font-semibold text-on-surface">添加标签</div>
              <div className="mt-1 text-xs text-on-surface-variant">
                将标签添加到 {customTagDialog.scopedKeys.length} 篇文献，标签会显示在“已翻译”同一栏。
              </div>
            </div>
            <div className="px-5 py-4">
              <label className="block text-xs font-medium text-on-surface-variant">
                标签名称
                <input
                  autoFocus
                  value={customTagDialog.value}
                  onChange={(e) => setCustomTagDialog((prev) => ({ ...prev, value: e.target.value }))}
                  placeholder="例如：理论基础、待精读、方法参考"
                  className="mt-2 w-full rounded-xl border border-outline-variant bg-surface-container-lowest px-3 py-2 text-sm text-on-surface outline-none transition focus:border-secondary focus:ring-2 focus:ring-secondary/20"
                  maxLength={32}
                />
              </label>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-outline-variant bg-surface-container-low px-5 py-3">
              <button
                type="button"
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-on-surface-variant hover:bg-surface-container"
                onClick={() => setCustomTagDialog({ visible: false, scopedKeys: [], value: '' })}
              >
                取消
              </button>
              <button
                type="submit"
                disabled={!customTagDialog.value.trim()}
                className="rounded-lg bg-secondary px-3 py-1.5 text-xs font-semibold text-on-secondary shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </form>
        </div>
      )}

      {mode === 'variables' && (
        <section className="space-y-4">
          <div className="flex items-center gap-3 mb-4">
            <Layers className="w-5 h-5 text-secondary" />
            <h3 className="text-xl font-medium text-on-surface">变量与概念</h3>
          </div>
          <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-3">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-outline" />
                <input
                  value={variableSearchQuery}
                  onChange={(e) => setVariableSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void runVariableSemanticSearch();
                  }}
                  placeholder="搜索变量名、概念、来源论文；回车语义搜索"
                  className="w-full rounded-lg border border-outline-variant bg-surface-container py-2 pl-9 pr-3 text-sm outline-none focus:border-secondary"
                />
              </div>
              <button
                onClick={() => void runVariableSemanticSearch()}
                disabled={!variableSearchQuery.trim() || variableSemanticLoading}
                className="rounded-lg bg-secondary px-3 py-2 text-sm font-semibold text-on-secondary disabled:opacity-50"
              >
                {variableSemanticLoading ? '语义检索中...' : '语义检索'}
              </button>
            </div>
            <div className="mt-2 text-xs text-on-surface-variant">
              本地匹配 {visibleVariableRows.length}/{variableRows.length} 个变量
            </div>
            {!!variableSemanticError && (
              <div className="mt-3 rounded-lg border border-error/30 bg-error-container/20 px-3 py-2 text-xs text-error">{variableSemanticError}</div>
            )}
            {semanticVariableResults.length > 0 && (
              <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
                {semanticVariableResults.map((row) => (
                  <div key={`${row.library_id}-${row.id}-${row.variable_name}`} className="rounded-lg border border-outline-variant bg-surface-container p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-on-surface">{row.variable_name || row.node_id || '未命名变量'}</div>
                        <div className="mt-1 text-[11px] font-mono text-outline">{row.library_id} · score {Number(row.score || 0).toFixed(3)}</div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <button
                          onClick={() => openSemanticVariableSource(row)}
                          className="rounded border border-outline-variant px-2 py-1 text-xs hover:border-secondary"
                        >
                          来源
                        </button>
                        <button
                          onClick={() => focusSemanticVariable(row)}
                          disabled={!row.node_id}
                          className="rounded bg-secondary px-2 py-1 text-xs text-on-secondary disabled:opacity-40"
                        >
                          图谱
                        </button>
                      </div>
                    </div>
                    <div className="mt-2 line-clamp-3 text-xs text-on-surface-variant">{row.concept_text || '暂无概念'}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead className="bg-surface-container-low border-b border-outline-variant"><tr><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">变量</th><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">概念</th><th className="px-4 py-3 text-[13px] font-mono uppercase text-outline">来源论文</th><th className="px-4 py-3" /></tr></thead>
              <tbody className="divide-y divide-outline-variant">
                {visibleVariableRows.map((row) => (
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



