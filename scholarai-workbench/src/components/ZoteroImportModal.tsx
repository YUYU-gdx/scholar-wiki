import { useState, useEffect, useMemo } from 'react';
import { Search, FileText, StickyNote, Highlighter, FolderTree, X, Database } from 'lucide-react';
import { useApp } from '../app-context';
import { api } from '../api';
import type { ZoteroItemInfo, ZoteroScanResponse, ZoteroCollectionInfo } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ZoteroImportModal({ open, onClose }: Props) {
  const { libraries, activeLibraryId } = useApp();

  const [dataDir, setDataDir] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ZoteroScanResponse | null>(null);
  const [scanError, setScanError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectedCollection, setSelectedCollection] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [previewItem, setPreviewItem] = useState<ZoteroItemInfo | null>(null);
  const [targetLibrary, setTargetLibrary] = useState(activeLibraryId || '');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState('');

  // Reset all state when modal opens
  useEffect(() => {
    if (open) {
      setDataDir('');
      setScanning(false);
      setScanResult(null);
      setScanError('');
      setSelectedIds(new Set());
      setSelectedCollection(null);
      setSearchQuery('');
      setPreviewItem(null);
      setTargetLibrary(activeLibraryId || '');
      setImporting(false);
      setImportResult('');
    }
  }, [open, activeLibraryId]);

  const handleScan = async () => {
    setScanning(true);
    setScanError('');
    setScanResult(null);
    setSelectedIds(new Set());
    setPreviewItem(null);
    setImportResult('');
    try {
      const result = await api.zotero.scan(dataDir.trim());
      setScanResult(result);
    } catch (err) {
      setScanError(String((err as Error)?.message || err));
    } finally {
      setScanning(false);
    }
  };

  // Build a flat tree from collection parent relationships
  const collectionTree = useMemo(() => {
    if (!scanResult) return [];
    const childrenMap = new Map<number | null, ZoteroCollectionInfo[]>();
    for (const col of scanResult.collections) {
      const parentId = col.parent_id;
      if (!childrenMap.has(parentId)) childrenMap.set(parentId, []);
      childrenMap.get(parentId)!.push(col);
    }
    const buildTree = (parentId: number | null, depth: number): Array<{ collection: ZoteroCollectionInfo; depth: number }> => {
      const children = childrenMap.get(parentId) || [];
      const result: Array<{ collection: ZoteroCollectionInfo; depth: number }> = [];
      for (const col of children) {
        result.push({ collection: col, depth });
        result.push(...buildTree(col.collection_id, depth + 1));
      }
      return result;
    };
    return buildTree(null, 0);
  }, [scanResult]);

  // Filter items by collection and search query
  const filteredItems = useMemo(() => {
    if (!scanResult) return [];
    let items = scanResult.items;

    if (selectedCollection !== null) {
      const colName = scanResult.collections.find(c => c.collection_id === selectedCollection)?.name || '';
      if (colName) {
        items = items.filter(item => item.collections.includes(colName));
      }
    }

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      items = items.filter(item =>
        item.title.toLowerCase().includes(q) ||
        item.creators.some(c =>
          `${c.first_name} ${c.last_name}`.toLowerCase().includes(q)
        )
      );
    }

    return items;
  }, [scanResult, selectedCollection, searchQuery]);

  const allSelected = filteredItems.length > 0 && filteredItems.every(item => selectedIds.has(item.item_id));

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allSelected) {
        filteredItems.forEach(item => next.delete(item.item_id));
      } else {
        filteredItems.forEach(item => next.add(item.item_id));
      }
      return next;
    });
  };

  const handleImport = async () => {
    if (selectedIds.size === 0 || !dataDir.trim()) return;
    setImporting(true);
    setImportResult('');
    try {
      const result = await api.zotero.importItems(dataDir.trim(), [...selectedIds], targetLibrary);
      setImportResult(`成功导入 ${result.count} 篇论文`);
    } catch (err) {
      setImportResult(`导入失败: ${String((err as Error)?.message || err)}`);
    } finally {
      setImporting(false);
    }
  };

  const formatCreators = (creators: ZoteroItemInfo['creators']) => {
    return creators.map(c => `${c.last_name} ${c.first_name}`).join('; ');
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-surface-container-lowest border border-outline-variant rounded-2xl shadow-2xl flex flex-col"
        style={{ width: '95vw', height: '85vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant shrink-0">
          <h2 className="text-lg font-bold text-on-surface">从 Zotero 导入</h2>
          <button onClick={onClose} className="text-outline hover:text-on-surface transition-colors p-1 rounded-lg hover:bg-surface-container" title="关闭">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ── Data directory + Scan button ──────────────────────── */}
        <div className="flex items-center gap-3 px-6 py-3 border-b border-outline-variant shrink-0">
          <label className="text-sm font-medium text-on-surface-variant whitespace-nowrap">数据目录:</label>
          <input
            type="text"
            value={dataDir}
            onChange={e => setDataDir(e.target.value)}
            placeholder="Zotero 数据目录路径"
            className="flex-1 bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-sm text-on-surface outline-none placeholder:text-outline"
          />
          <button
            onClick={handleScan}
            disabled={scanning}
            className="bg-secondary hover:bg-secondary/90 text-on-secondary px-5 py-1.5 rounded-lg text-sm font-medium transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {scanning ? (
              <>
                <div className="w-4 h-4 border-2 border-on-secondary border-t-transparent rounded-full animate-spin" />
                扫描中...
              </>
            ) : (
              '扫描'
            )}
          </button>
        </div>

        {/* ── Error / result banners ────────────────────────────── */}
        {scanError && (
          <div className="mx-6 mt-3 bg-error-container/20 border border-error/30 rounded-lg px-4 py-2 text-sm text-error shrink-0">
            {scanError}
          </div>
        )}
        {importResult && (
          <div className={`mx-6 mt-3 rounded-lg px-4 py-2 text-sm shrink-0 ${
            importResult.includes('失败')
              ? 'bg-error-container/20 border border-error/30 text-error'
              : 'bg-tertiary-container/20 border border-tertiary/30 text-on-tertiary-container'
          }`}>
            {importResult}
          </div>
        )}

        {/* ── Three-column body ─────────────────────────────────── */}
        <div className="flex flex-1 min-h-0">
          {/* Left: Collections sidebar */}
          <div className="w-56 border-r border-outline-variant flex flex-col shrink-0">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-outline-variant">
              <FolderTree className="w-4 h-4 text-outline" />
              <span className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">文件夹</span>
            </div>
            <div className="flex-1 overflow-y-auto py-2">
              <button
                onClick={() => { setSelectedCollection(null); setSearchQuery(''); }}
                className={`w-full text-left px-4 py-1.5 text-sm transition-colors ${
                  selectedCollection === null
                    ? 'bg-secondary-container/20 text-on-secondary-container font-medium'
                    : 'text-on-surface hover:bg-surface-container/50'
                }`}
              >
                全部
              </button>
              {collectionTree.map(({ collection, depth }) => (
                <button
                  key={collection.collection_id}
                  onClick={() => setSelectedCollection(collection.collection_id)}
                  className={`w-full text-left py-1.5 text-sm transition-colors ${
                    selectedCollection === collection.collection_id
                      ? 'bg-secondary-container/20 text-on-secondary-container font-medium'
                      : 'text-on-surface hover:bg-surface-container/50'
                  }`}
                  style={{ paddingLeft: `${12 + depth * 16}px`, paddingRight: '16px' }}
                >
                  {collection.name}
                </button>
              ))}
            </div>
          </div>

          {/* Center: Items table */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-outline-variant">
              <Search className="w-4 h-4 text-outline shrink-0" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="搜索标题或作者..."
                className="flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-outline"
              />
              {scanResult && (
                <span className="text-xs text-on-surface-variant font-mono whitespace-nowrap">
                  {filteredItems.length} / {scanResult.total_count}
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              <table className="w-full text-left border-collapse">
                <thead className="sticky top-0 bg-surface-container-lowest z-10">
                  <tr className="text-xs font-mono font-black text-outline uppercase tracking-widest border-b border-outline-variant">
                    <th className="w-[36px] px-2 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        disabled={filteredItems.length === 0}
                      />
                    </th>
                    <th className="px-3 py-2">标题</th>
                    <th className="px-3 py-2">作者</th>
                    <th className="px-3 py-2 w-[60px]">年</th>
                    <th className="px-3 py-2 w-[40px] text-center">PDF</th>
                    <th className="px-3 py-2 w-[60px] text-center">笔</th>
                    <th className="px-3 py-2 w-[80px]">标签</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant/10">
                  {!scanResult ? (
                    <tr>
                      <td colSpan={7} className="px-6 py-12 text-center text-on-surface-variant text-sm">
                        请先扫描 Zotero 数据目录
                      </td>
                    </tr>
                  ) : filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-6 py-12 text-center text-on-surface-variant text-sm">
                        无匹配条目
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((item) => (
                      <tr
                        key={item.item_id}
                        className={`hover:bg-surface-container-low/30 transition-colors cursor-pointer ${
                          previewItem?.item_id === item.item_id ? 'bg-secondary-container/10' : ''
                        }`}
                        onClick={() => setPreviewItem(item)}
                      >
                        <td className="px-2 py-2 text-center" onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(item.item_id)}
                            onChange={() => toggleSelect(item.item_id)}
                          />
                        </td>
                        <td className="px-3 py-2 text-sm font-medium text-on-surface truncate max-w-[200px]" title={item.title}>
                          {item.title || '-'}
                        </td>
                        <td className="px-3 py-2 text-sm text-on-surface-variant truncate max-w-[120px]">
                          {item.creators.length > 0
                            ? formatCreators(item.creators.slice(0, 2)) + (item.creators.length > 2 ? ' et al.' : '')
                            : '-'}
                        </td>
                        <td className="px-3 py-2 text-sm text-on-surface-variant">
                          {item.date ? item.date.slice(0, 4) : '-'}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {item.pdf_paths.length > 0 ? (
                            <FileText className="w-4 h-4 text-secondary inline-block" />
                          ) : (
                            <span className="text-outline">-</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <div className="flex items-center justify-center gap-1">
                            {item.note_count > 0 && (
                              <span className="flex items-center gap-0.5 text-xs text-on-surface-variant" title={`${item.note_count} 条笔记`}>
                                <StickyNote className="w-3 h-3" />
                                {item.note_count}
                              </span>
                            )}
                            {item.annotation_count > 0 && (
                              <span className="flex items-center gap-0.5 text-xs text-on-surface-variant" title={`${item.annotation_count} 条标注`}>
                                <Highlighter className="w-3 h-3" />
                                {item.annotation_count}
                              </span>
                            )}
                            {item.note_count === 0 && item.annotation_count === 0 && (
                              <span className="text-outline">-</span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-sm text-on-surface-variant truncate max-w-[80px]" title={item.collections.join(', ')}>
                          {item.collections.length > 0 ? item.collections[0] : '-'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right: Preview panel */}
          <div className="w-80 border-l border-outline-variant flex flex-col shrink-0">
            <div className="px-4 py-3 border-b border-outline-variant">
              <span className="text-xs font-bold text-on-surface uppercase tracking-widest font-mono">详情预览</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {previewItem ? (
                <div className="space-y-3 text-sm">
                  <h3 className="font-bold text-on-surface leading-snug">{previewItem.title}</h3>

                  {previewItem.creators.length > 0 && (
                    <div className="text-xs text-on-surface-variant space-y-0.5">
                      {previewItem.creators.map((c, i) => (
                        <div key={i}>
                          <span className="font-medium">{c.last_name}</span>, {c.first_name}{' '}
                          <span className="text-outline">({c.creator_type})</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {previewItem.date && (
                    <div>
                      <span className="text-on-surface-variant">日期: </span>
                      <span className="text-on-surface">{previewItem.date}</span>
                    </div>
                  )}

                  {previewItem.publication_title && (
                    <div>
                      <span className="text-on-surface-variant">期刊: </span>
                      <span className="text-on-surface">{previewItem.publication_title}</span>
                    </div>
                  )}

                  {(previewItem.volume || previewItem.issue || previewItem.pages) && (
                    <div className="text-on-surface">
                      {previewItem.volume && <span>卷 {previewItem.volume}</span>}
                      {previewItem.issue && <span>({previewItem.issue})</span>}
                      {previewItem.pages && <span>: {previewItem.pages}</span>}
                    </div>
                  )}

                  {previewItem.doi && (
                    <div className="font-mono text-xs text-on-surface-variant truncate" title={previewItem.doi}>
                      DOI: {previewItem.doi}
                    </div>
                  )}

                  {previewItem.abstract && (
                    <div>
                      <p className="text-xs text-on-surface-variant leading-relaxed line-clamp-6">
                        {previewItem.abstract}
                      </p>
                    </div>
                  )}

                  {previewItem.collections.length > 0 && (
                    <div>
                      <span className="text-on-surface-variant">集合: </span>
                      <span className="text-on-surface text-xs">{previewItem.collections.join(', ')}</span>
                    </div>
                  )}

                  {previewItem.pdf_paths[0] && (
                    <div className="font-mono text-xs text-on-surface-variant truncate" title={previewItem.pdf_paths[0]}>
                      {previewItem.pdf_paths[0]}
                    </div>
                  )}

                  <div className="flex gap-4 text-xs text-on-surface-variant pt-1">
                    <span>笔记: {previewItem.note_count}</span>
                    <span>标注: {previewItem.annotation_count}</span>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-on-surface-variant text-center py-8">
                  选择条目查看详情
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Bottom bar ────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-3 border-t border-outline-variant shrink-0">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-outline" />
            <label className="text-sm text-on-surface-variant">目标文献库:</label>
            <select
              value={targetLibrary}
              onChange={e => setTargetLibrary(e.target.value)}
              className="bg-surface-container border border-outline-variant rounded-lg px-3 py-1.5 text-sm text-on-surface outline-none"
            >
              {libraries.length === 0 ? (
                <option value="">（无文献库）</option>
              ) : (
                libraries.map(lib => (
                  <option key={lib.library_id} value={lib.library_id}>
                    {lib.library_id} ({lib.paper_count} 篇)
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-5 py-2 bg-surface-container border border-outline-variant rounded-lg text-sm text-on-surface font-medium hover:bg-surface-container-high transition-all"
            >
              取消
            </button>
            <button
              onClick={handleImport}
              disabled={selectedIds.size === 0 || importing}
              className="bg-secondary hover:bg-secondary/90 text-on-secondary px-5 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 flex items-center gap-2"
            >
              {importing ? (
                <>
                  <div className="w-4 h-4 border-2 border-on-secondary border-t-transparent rounded-full animate-spin" />
                  导入中...
                </>
              ) : (
                `导入选中 (${selectedIds.size})`
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
