interface DesktopShell {
  platform: string;
  runtime: string;
  getBackendPort(): Promise<number>;
  getBackendUrl(): Promise<string>;
  getBackendUrlSync(): string;
  restartBackend(): Promise<number>;
  openLocalPath(targetPath: string): Promise<{ ok: boolean; error?: string }>;
  readLocalFile(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
  readLocalText(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
  writeLocalText(filePath: string, text: string): Promise<{ ok: boolean; size?: number; error?: string }>;
  resolveLocalAsset(markdownPath: string, relPath: string): Promise<{ ok: boolean; path?: string; error?: string }>;
  grepWorkspace(pattern: string, libraryId: string): Promise<{ ok: boolean; results: Array<{ filePath: string; fileName: string; lineNumber: number; snippet: string }>; error?: string }>;
  resolvePaperPaths(paperId: string, libraryId: string): Promise<{ ok: boolean; files?: Record<string, { path: string; name: string; size_bytes: number }>; content_list_v2_path?: string; status?: number; error?: string }>;
  watchFile(filePath: string): Promise<{ ok: boolean; error?: string }>;
  unwatchFile(filePath: string): Promise<{ ok: boolean }>;
  onFileChanged(callback: (payload: { path: string; event: string }) => void): () => void;
}

declare global {
  interface Window {
    desktopShell?: DesktopShell;
  }
}

export {};
