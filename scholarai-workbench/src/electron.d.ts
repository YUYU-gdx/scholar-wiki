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
}

declare global {
  interface Window {
    desktopShell?: DesktopShell;
  }
}

export {};
