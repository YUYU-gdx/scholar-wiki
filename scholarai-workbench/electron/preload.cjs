const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  runtime: "electron",
  getBackendPort: () => ipcRenderer.invoke("get-backend-port"),
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  getBackendUrlSync: () => ipcRenderer.sendSync("get-backend-url-sync"),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLocalPath: (targetPath) => ipcRenderer.invoke("open-local-path", targetPath),
  readLocalFile: (filePath) => ipcRenderer.invoke("read-local-file", filePath),
  readLocalText: (filePath) => ipcRenderer.invoke("read-local-text", filePath),
  writeLocalText: (filePath, text) => ipcRenderer.invoke("write-local-text", filePath, text),
  resolveLocalAsset: (markdownPath, relPath) => ipcRenderer.invoke("resolve-local-asset", markdownPath, relPath),
  grepWorkspace: (pattern, libraryId) => ipcRenderer.invoke("grep-workspace", pattern, libraryId),
  resolvePaperPaths: (paperId, libraryId) => ipcRenderer.invoke("resolve-paper-paths", paperId, libraryId),
  watchFile: (filePath) => ipcRenderer.invoke("watch-file", filePath),
  unwatchFile: (filePath) => ipcRenderer.invoke("unwatch-file", filePath),
  onFileChanged: (callback) => {
    const handler = (_evt, payload) => callback(payload);
    ipcRenderer.on("file-changed", handler);
    return () => ipcRenderer.removeListener("file-changed", handler);
  },
  runInTerminal: (packageName, binary, displayName) => ipcRenderer.invoke("run-in-terminal", packageName, binary, displayName),
});
