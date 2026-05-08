const { contextBridge, ipcRenderer } = require("electron");

// Backend URL is predictable: port 8013 on localhost.
// Electron main process picks a port in 8013-8017 range.
const BACKEND_BASE = "http://127.0.0.1:8013";

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  runtime: "electron",
  getBackendPort: () => ipcRenderer.invoke("get-backend-port"),
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  getBackendUrlSync: () => BACKEND_BASE,
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLocalPath: (targetPath) => ipcRenderer.invoke("open-local-path", targetPath),
  readLocalFile: (filePath) => ipcRenderer.invoke("read-local-file", filePath),
  readLocalText: (filePath) => ipcRenderer.invoke("read-local-text", filePath),
  writeLocalText: (filePath, text) => ipcRenderer.invoke("write-local-text", filePath, text),
  resolveLocalAsset: (markdownPath, relPath) => ipcRenderer.invoke("resolve-local-asset", markdownPath, relPath),
  resolvePaperPaths: (paperId, libraryId) => ipcRenderer.invoke("resolve-paper-paths", paperId, libraryId),
  watchFile: (filePath) => ipcRenderer.invoke("watch-file", filePath),
  unwatchFile: (filePath) => ipcRenderer.invoke("unwatch-file", filePath),
  onFileChanged: (callback) => {
    const handler = (_evt, payload) => callback(payload);
    ipcRenderer.on("file-changed", handler);
    return () => ipcRenderer.removeListener("file-changed", handler);
  },
});
