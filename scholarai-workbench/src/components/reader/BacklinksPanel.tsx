import { useState, useEffect } from 'react';
import { ExternalLink } from 'lucide-react';
import type { BacklinkEntry } from './types';

interface BacklinksPanelProps {
  paperId: string;
  libraryId: string;
  currentMarkdownPath?: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function BacklinksPanel({ paperId, libraryId, currentMarkdownPath = '', isOpen, onToggle }: BacklinksPanelProps) {
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
    const mdPath = String(currentMarkdownPath || '').trim();
    const mdName = mdPath.split(/[\\/]/).pop() || '';
    const titleNoExt = mdName.replace(/\.md$/i, '');
    const inboundPatterns = Array.from(new Set([
      `[[@${paperId}]]`,
      mdPath,
      mdName,
      `${titleNoExt}.md`,
      `[[${titleNoExt}]]`,
      `](${mdName})`,
      `.md)`,
    ].filter(Boolean)));

    const outboundFromCurrent = async (): Promise<BacklinkEntry[]> => {
      if (!mdPath) return [];
      const txt = await shell.readLocalText(mdPath);
      if (!txt?.ok || typeof txt.data !== 'string') return [];
      const out: BacklinkEntry[] = [];
      const lines = String(txt.data).split(/\r?\n/);
      const mdLinkRe = /\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)/gi;
      lines.forEach((line, idx) => {
        let m: RegExpExecArray | null;
        while ((m = mdLinkRe.exec(line)) !== null) {
          const target = String(m[1] || '').trim();
          if (!target) continue;
          out.push({
            filePath: mdPath,
            fileName: mdName || 'current.md',
            lineNumber: idx + 1,
            snippet: `outbound -> ${target}`,
          });
        }
      });
      return out;
    };

    Promise.all([
      outboundFromCurrent(),
      Promise.all(inboundPatterns.map((p) => shell.grepWorkspace(p, libraryId).catch(() => ({ ok: false, results: [] })))),
    ]).then(([outbound, inboundBatch]) => {
      const inbound: BacklinkEntry[] = [];
      for (const row of inboundBatch) {
        if (row?.ok && Array.isArray(row.results)) inbound.push(...row.results);
      }
      const normalizedCurrent = mdPath.toLowerCase();
      const filteredInbound = inbound.filter((r) => String(r.filePath || '').toLowerCase() !== normalizedCurrent);
      const dedupe = new Map<string, BacklinkEntry>();
      for (const e of [...outbound, ...filteredInbound]) {
        const k = `${e.filePath}::${e.lineNumber}::${e.snippet}`;
        if (!dedupe.has(k)) dedupe.set(k, e);
      }
      setEntries(Array.from(dedupe.values()));
      setLoading(false);
    }).catch(() => {
      setEntries([]);
      setLoading(false);
    });
  }, [isOpen, paperId, libraryId, currentMarkdownPath]);

  if (!isOpen) return null;

  return (
    <div className="w-64 shrink-0 border-l border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-3">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-medium text-on-surface-variant">反向链接 ({entries.length})</h4>
          <button className="text-xs text-outline hover:text-on-surface" onClick={onToggle}>×</button>
        </div>
        {loading && <p className="text-xs text-outline">搜索中...</p>}
        {!loading && entries.length === 0 && <p className="text-xs text-outline">未找到反向链接</p>}
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
            <pre className="text-xs text-on-surface-variant mt-0.5 whitespace-pre-wrap break-all">{entry.snippet}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}
