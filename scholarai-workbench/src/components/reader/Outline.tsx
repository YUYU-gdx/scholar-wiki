import { useEffect, useState, useRef, useCallback } from 'react';
import type { OutlineItem } from './types';

interface OutlineProps {
  content: string;
  activeLine?: number;
  onGoToLine?: (line: number) => void;
}

function parseOutline(text: string): OutlineItem[] {
  const lines = text.split('\n');
  const items: OutlineItem[] = [];
  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^(#{1,6})\s+(.+)/);
    if (!match) continue;
    const level = match[1].length;
    const headingText = match[2].trim();
    const id = `h-${i}-${headingText.toLowerCase().replace(/[^\w一-鿿]+/g, '-').replace(/(^-|-$)/g, '')}`;
    items.push({ level, text: headingText, line: i, id });
  }
  return items;
}

const LEVEL_PAD = 14; // px per indent level
const BASE_PAD = 8;

export default function Outline({ content, activeLine = -1, onGoToLine }: OutlineProps) {
  const [items, setItems] = useState<OutlineItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    setItems(parseOutline(content));
  }, [content]);

  // Track visible headings via IntersectionObserver
  const setupObserver = useCallback(() => {
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    const host = document.querySelector('.reader-markdown');
    if (!host) return;

    const headingSelector = 'h1, h2, h3, h4, h5, h6';
    const headings = host.querySelectorAll(headingSelector);
    if (headings.length === 0) return;

    const visibleHeadings = new Map<Element, string>();

    observerRef.current = new IntersectionObserver(
      (entries) => {
        // Collect all currently intersecting headings
        for (const entry of entries) {
          const id = visibleHeadings.get(entry.target);
          if (!id) continue;
          if (entry.isIntersecting) {
            // Find the topmost visible heading
            const allVisible = Array.from(visibleHeadings.entries())
              .filter(([el]) => {
                const rect = el.getBoundingClientRect();
                return rect.top < window.innerHeight * 0.4 && rect.bottom > 0;
              })
              .sort(([a], [b]) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
            if (allVisible.length > 0) {
              setActiveId(allVisible[0][1]);
            }
            break;
          }
        }
      },
      { rootMargin: '-10% 0px -60% 0px' },
    );

    for (const heading of headings) {
      const lineStr = heading.getAttribute('data-src-line-start');
      if (lineStr == null) continue;
      const line = Number(lineStr);
      const item = items.find((it) => it.line === line);
      if (item) {
        visibleHeadings.set(heading, item.id);
        observerRef.current.observe(heading);
      }
    }
  }, [items]);

  // Re-attach observer after DOM paint
  useEffect(() => {
    const t = setTimeout(() => setupObserver(), 50);
    return () => {
      clearTimeout(t);
      observerRef.current?.disconnect();
    };
  }, [setupObserver]);

  // Accept explicit activeLine from parent (e.g. CM6 editor cursor)
  useEffect(() => {
    if (activeLine < 0) return;
    const hit = items.find((it) => it.line === activeLine);
    if (hit) setActiveId(hit.id);
  }, [activeLine, items]);

  // Auto-scroll active item into view
  useEffect(() => {
    if (!activeId || !containerRef.current) return;
    const el = containerRef.current.querySelector(`[data-outline-id="${CSS.escape(activeId)}"]`);
    if (el) {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [activeId]);

  if (items.length === 0) {
    return (
      <div className="w-56 shrink-0 border-r border-outline-variant bg-surface-container-lowest p-3">
        <p className="text-xs text-outline">无标题</p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="w-56 shrink-0 border-r border-outline-variant bg-surface-container-lowest overflow-y-auto custom-scrollbar"
    >
      <div className="pt-3 pb-4">
        <h4 className="text-xs font-semibold text-outline uppercase tracking-widest px-4 mb-2">
          大纲
        </h4>
        {items.map((item) => {
          const isActive = item.id === activeId;
          const padLeft = BASE_PAD + (item.level - 1) * LEVEL_PAD;

          return (
            <button
              key={item.id}
              data-outline-id={item.id}
              className={`outline-item block w-full text-left transition-colors duration-150 relative ${
                isActive
                  ? 'text-on-surface font-semibold bg-surface-container'
                  : 'text-on-surface-variant hover:bg-surface-container-low'
              }`}
              style={{
                paddingLeft: `${padLeft}px`,
                paddingRight: '12px',
                paddingTop: item.level <= 2 ? '5px' : '3px',
                paddingBottom: item.level <= 2 ? '5px' : '3px',
                fontSize: item.level === 1 ? '13px' : item.level === 2 ? '12.5px' : '12px',
                fontWeight: item.level === 1 ? 600 : item.level === 2 ? 500 : 400,
              }}
              onClick={() => {
                onGoToLine?.(item.line);
                // Also try scrolling the rendered heading into view
                const host = document.querySelector('.reader-markdown');
                const heading = host?.querySelector(`[data-src-line-start="${item.line}"]`);
                heading?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              title={item.text}
            >
              {/* Indentation guide lines */}
              {Array.from({ length: item.level - 1 }).map((_, i) => (
                <span
                  key={i}
                  className="outline-guide"
                  style={{
                    left: `${BASE_PAD + i * LEVEL_PAD + 3}px`,
                  }}
                />
              ))}
              {/* Active indicator */}
              {isActive && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-secondary rounded-r-full"
                />
              )}
              <span className="block truncate">{item.text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
