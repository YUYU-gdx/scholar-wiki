const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("desktopShell", {
  platform: process.platform,
  runtime: "electron",
});

