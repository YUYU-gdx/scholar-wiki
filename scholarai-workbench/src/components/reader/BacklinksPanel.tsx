import { useState, useEffect } from 'react';
import { ExternalLink } from 'lucide-react';
import type { BacklinkEntry } from './types';

interface BacklinksPanelProps {
  paperId: string;
  libraryId: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function BacklinksPanel({ paperId, libraryId, isOpen, onToggle }: BacklinksPanelProps) {
  const [entries, setEntries] = useState<BacklinkEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isOpen || !paperId) {
      setEntries([]);
      setLoading(false);
      return;
    }
    const shell = window.desktopShell;
    if (!shell || shell.runtime !== 'electron') {
      setEntries([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    const pattern = `[[@${paperId}]]`;
    shell.grepWorkspace(pattern, libraryId).then((r: any) => {
      if (r?.ok) setEntries(r.results || []);
      else setEntries([]);
      setLoading(false);
    }).catch(() => {
      setEntries([]);
      setLoading(false);
    });
  }, [isOpen, paperId, libraryId]);

  if (!isOpen) return null;

  return (
    <div className="w-64 shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-on-surface-variant">Backlinks ({entries.length})</h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>
        {loading && <p className="text-xs text-outline">Searching...</p>}
        {!loading && entries.length === 0 && <p className="text-xs text-outline">No backlinks found</p>}
        {entries.map((entry, i) => (
          <div key={i} className="mb-2 p-2 rounded bg-surface-container text-xs">
            <div className="flex items-center gap-1 mb-0.5">
              <span className="text-on-surface font-mono truncate" title={entry.fileName}>{entry.fileName}</span>
              <span className="text-outline">:{entry.lineNumber}</span>
              <button
                className="ml-auto text-outline hover:text-primary"
                onClick={() => window.dispatchEvent(new CustomEvent('open-reader-file', { detail: { path: entry.filePath } }))}
              >
                <ExternalLink className="w-3 h-3" />
              </button>
            </div>
            <pre className="text-[10px] text-on-surface-variant mt-0.5 whitespace-pre-wrap break-all">{entry.snippet}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}

