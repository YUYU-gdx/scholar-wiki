import { useEffect, useMemo, useRef } from 'react';
import { useApp } from '../App';

export default function GraphView() {
  const iframeRevRef = useRef<string>(String(Date.now()));

  const {
    activeLibraryId,
    selectedLibraryIds,
    setSelectedLibraryIds,
    setActiveLibraryId,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedPaperRawId,
    setReaderReturnView,
    setCurrentView,
  } = useApp();

  useEffect(() => {
    function onMessage(evt: MessageEvent) {
      const data = evt.data as { type?: string; payload?: Record<string, unknown> } | null;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'KN_GRAPH_OPEN_READER') {
        const paperId = String(data.payload?.paperId || '');
        const libraryId = String(data.payload?.libraryId || activeLibraryId || 'supply_chain');
        if (!paperId) return;
        const rawType = String(data.payload?.preferredType || '');
        const preferredType = (['pdf', 'markdown', 'html'].includes(rawType))
          ? rawType as 'pdf' | 'markdown' | 'html'
          : null;
        setSelectedPaperId(paperId);
        setSelectedPaperLibraryId(libraryId);
        setSelectedPaperPreferredType(preferredType);
        setSelectedPaperRawId(String(data.payload?.rawPaperId || '') || null);
        setReaderReturnView('graph');
        setCurrentView('reader');
        return;
      }

      if (data.type === 'KN_GRAPH_SET_LIBRARIES') {
        const idsRaw = Array.isArray(data.payload?.libraryIds) ? data.payload?.libraryIds : [];
        const ids = idsRaw.map((v) => String(v)).filter(Boolean);
        if (!ids.length) return;

        const current = selectedLibraryIds.length ? selectedLibraryIds : [activeLibraryId || 'supply_chain'];
        const same = current.length === ids.length && current.every((v, i) => v === ids[i]);
        if (same) return;

        setSelectedLibraryIds(ids);
        setActiveLibraryId(ids[0]);
      }
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [
    activeLibraryId,
    selectedLibraryIds,
    setActiveLibraryId,
    setCurrentView,
    setSelectedLibraryIds,
    setSelectedPaperId,
    setSelectedPaperLibraryId,
    setSelectedPaperPreferredType,
    setSelectedPaperRawId,
    setReaderReturnView,
  ]);

  const src = useMemo(() => {
    const ids = selectedLibraryIds.length ? selectedLibraryIds : [activeLibraryId || 'supply_chain'];
    const qs = new URLSearchParams();
    qs.set('library_id', activeLibraryId || ids[0] || 'supply_chain');
    qs.set('active_library_id', activeLibraryId || ids[0] || 'supply_chain');
    qs.set('library_ids', ids.join(','));
    qs.set('ui_rev', iframeRevRef.current);
    return `/frontend_legacy/graph_3d/index.html?${qs.toString()}`;
  }, [activeLibraryId, selectedLibraryIds]);

  return (
    <div className="flex-1 bg-surface-container-low">
      <iframe title="Legacy Graph 3D" src={src} className="w-full h-full border-0" />
    </div>
  );
}
