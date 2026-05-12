import { useEffect, useState, useRef } from 'react';
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
    const id = headingText.toLowerCase().replace(/[^\w一-鿿]+/g, '-').replace(/(^-|-$)/g, '');
    items.push({ level, text: headingText, line: i, id });
  }
  return items;
}

export default function Outline({ content, activeLine = -1, onGoToLine }: OutlineProps) {
  const [items, setItems] = useState<OutlineItem[]>([]);

  useEffect(() => {
    setItems(parseOutline(content));
  }, [content]);

  if (items.length === 0) {
    return (
      <div className="w-48 shrink-0 border-r border-outline-variant bg-surface-container-lowest p-3">
        <p className="text-xs text-outline">无标题</p>
      </div>
    );
  }

  return (
    <div className="w-48 shrink-0 border-r border-outline-variant bg-surface-container-lowest overflow-y-auto">
      <div className="p-2">
        <h4 className="text-[11px] font-medium text-on-surface-variant px-1.5 py-1 mb-1">大纲</h4>
        {items.map((item) => {
          const isExact = item.line === activeLine;
          return (
            <button
              key={`${item.line}-${item.text}`}
              className={`block w-full text-left text-xs px-1.5 py-0.5 rounded truncate transition-colors hover:bg-surface-container-low ${
                isExact
                  ? 'text-primary font-medium bg-primary-container/30'
                  : 'text-on-surface-variant'
              }`}
              style={{ paddingLeft: `${4 + (item.level - 1) * 12}px` }}
              onClick={() => onGoToLine?.(item.line)}
              title={item.text}
            >
              {item.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}
