interface DesktopShell {
  platform: string;
  runtime: string;
  getBackendPort(): Promise<number>;
  getBackendUrl(): Promise<string>;
  restartBackend(): Promise<number>;
  openLocalPath(targetPath: string): Promise<{ ok: boolean; error?: string }>;
  readLocalFile(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
  readLocalText(filePath: string): Promise<{ ok: boolean; data?: string; size?: number; error?: string }>;
  writeLocalText(filePath: string, text: string): Promise<{ ok: boolean; size?: number; error?: string }>;
  resolveLocalAsset(markdownPath: string, relPath: string): Promise<{ ok: boolean; path?: string; error?: string }>;
  resolvePaperPaths(paperId: string, libraryId: string): Promise<{ ok: boolean; files?: Record<string, { path: string; name: string; size_bytes: number }>; status?: number; error?: string }>;
  resolvePaper(filesPayload: any): Promise<{ ok: boolean; type?: string; path?: string; name?: string; data?: string; size?: number; error?: string }>;
}

declare global {
  interface Window {
    desktopShell?: DesktopShell;
  }
}

export {};
