import { X, FileText, FileType } from 'lucide-react';
import type { TabDescriptor } from './types';

interface TabBarProps {
  tabs: TabDescriptor[];
  activeTabId: string | null;
  onSelectTab: (tabId: string) => void;
  onCloseTab: (tabId: string) => void;
}

export default function TabBar({ tabs, activeTabId, onSelectTab, onCloseTab }: TabBarProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="flex items-center gap-0 px-2 py-0 border-b border-outline-variant bg-surface-container-lowest overflow-x-auto">
      {tabs.map((tab) => {
        const isActive = tab.id === activeTabId;
        const Icon = tab.type === 'pdf' ? FileType : FileText;
        return (
          <button
            key={tab.id}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-outline-variant transition-colors min-w-0 max-w-[200px] ${
              isActive
                ? 'bg-surface-container text-on-surface font-medium'
                : 'text-on-surface-variant hover:bg-surface-container-low'
            }`}
            onClick={() => onSelectTab(tab.id)}
            title={tab.path}
          >
            <Icon className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">{tab.title}</span>
            <X
              className="w-3 h-3 shrink-0 ml-0.5 hover:text-error rounded-sm"
              onClick={(e) => {
                e.stopPropagation();
                onCloseTab(tab.id);
              }}
            />
          </button>
        );
      })}
    </div>
  );
}
