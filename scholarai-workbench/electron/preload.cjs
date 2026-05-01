const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  runtime: "electron",
  getBackendPort: () => ipcRenderer.invoke("get-backend-port"),
  getBackendUrl: () => ipcRenderer.invoke("get-backend-url"),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLocalPath: (targetPath) => ipcRenderer.invoke("open-local-path", targetPath),
  readLocalFile: (filePath) => ipcRenderer.invoke("read-local-file", filePath),
  readLocalText: (filePath) => ipcRenderer.invoke("read-local-text", filePath),
});
