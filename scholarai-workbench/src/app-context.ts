import { createContext, useContext } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import type { View, GraphFull, ChatSession, LiteratureLibrary, PipelineJob } from './types';

export type AppContextType = {
  currentView: View;
  setCurrentView: (v: View) => void;
  graphData: GraphFull | null;
  setGraphData: Dispatch<SetStateAction<GraphFull | null>>;
  selectedNodeId: string | null;
  selectedNodeLibraryId: string;
  setSelectedNodeId: (id: string | null) => void;
  setSelectedNodeLibraryId: (id: string) => void;
  selectedPaperId: string | null;
  selectedPaperLibraryId: string;
  setSelectedPaperId: (id: string | null) => void;
  setSelectedPaperLibraryId: (id: string) => void;
  selectedPaperPreferredType: 'pdf' | 'markdown' | 'html' | null;
  setSelectedPaperPreferredType: (type: 'pdf' | 'markdown' | 'html' | null) => void;
  selectedPaperRawId: string | null;
  setSelectedPaperRawId: (id: string | null) => void;
  readerReturnView: 'library' | 'graph';
  setReaderReturnView: (v: 'library' | 'graph') => void;
  sessions: ChatSession[];
  setSessions: Dispatch<SetStateAction<ChatSession[]>>;
  activeSessionId: string | null;
  setActiveSessionId: (id: string | null) => void;
  libraries: LiteratureLibrary[];
  activeLibraryId: string;
  setActiveLibraryId: (id: string) => void;
  selectedLibraryIds: string[];
  setSelectedLibraryIds: Dispatch<SetStateAction<string[]>>;
  pipelineJobs: PipelineJob[];
  setPipelineJobs: Dispatch<SetStateAction<PipelineJob[]>>;
  graphLoading: boolean;
  paperFileCache: Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }>;
  setPaperFileCache: Dispatch<SetStateAction<Record<string, { pdf: boolean; markdown: boolean; html: boolean; loaded: boolean }>>>;
};

export const AppContext = createContext<AppContextType>(null!);

export function useApp(): AppContextType {
  return useContext(AppContext);
}
