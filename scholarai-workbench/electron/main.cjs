const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { promisify } = require("node:util");
const execFileAsync = promisify(execFile);

const HOST = "127.0.0.1";
const BASE_PORT = Number(process.env.KN_GRAPH_PORT || 8013);
const START_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 800;
const MAX_PORT_SCAN = 20;

let backendProc = null;
let mainWindow = null;
let runtimePort = BASE_PORT;
let stoppingBackendPromise = null;
let quitInProgress = false;
let backendStartedByUs = false;

function appUrl() {
  // Load built frontend from disk (no Vite dev server needed)
  const distIndex = path.join(__dirname, "..", "dist", "index.html");
  if (fs.existsSync(distIndex)) {
    return `file:///${distIndex.replace(/\\/g, "/")}`;
  }
  // Fallback: try Vite dev server for development
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) return devUrl;
  // Last resort: let backend serve static files
  return `http://${HOST}:${runtimePort}`;
}

function healthUrl(port) {
  return `http://${HOST}:${port}/healthz`;
}

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.on("error", () => resolve(false));
    server.listen({ host: HOST, port }, () => {
      server.close(() => resolve(true));
    });
  });
}

async function isBackendAlive(port) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    const resp = await fetch(healthUrl(port), { signal: controller.signal });
    clearTimeout(timer);
    return resp.ok;
  } catch (_err) {
    return false;
  }
}

async function pickRuntimePort(base) {
  for (let i = 0; i <= MAX_PORT_SCAN; i += 1) {
    const candidate = base + i;
    const available = await isPortAvailable(candidate);
    if (available) return candidate;
  }
  throw new Error(`no_available_port_in_range:${base}-${base + MAX_PORT_SCAN}`);
}

function getRepoRoot() {
  return path.resolve(__dirname, "..", "..");
}

function getDefaultDataDir() {
  const envDir = String(process.env.KN_GRAPH_DATA_DIR || "").trim();
  if (envDir) return envDir;
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA
      || process.env.APPDATA
      || path.join(process.env.HOME || process.env.USERPROFILE || ".", "AppData", "Local");
    const suffix = app.isPackaged ? "KNGraphApp" : "KNGraphApp-dev";
    return path.join(base, suffix);
  }
  return path.join(process.env.HOME || process.env.USERPROFILE || ".", app.isPackaged ? ".kn_graph" : ".kn_graph-dev");
}

function buildPythonEnv(repoRoot) {
  const prev = String(process.env.PYTHONPATH || "").trim();
  const sep = process.platform === "win32" ? ";" : ":";
  const pythonPath = prev ? `${repoRoot}${sep}${prev}` : repoRoot;
  const dataDir = getDefaultDataDir();
  const installRoot = app.isPackaged ? path.dirname(process.execPath) : repoRoot;
  const workspacesDir = path.join(installRoot, "workspaces");
  return {
    ...process.env,
    PYTHONPATH: pythonPath,
    KN_GRAPH_DATA_DIR: dataDir,
    KN_GRAPH_WORKSPACES_DIR: workspacesDir,
  };
}

function safeReadJson(filePath) {
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    if (!raw || raw.indexOf("\u0000") !== -1) return null;
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

function collectGraphViewsFiles(outputsRoot) {
  const out = [];
  const stack = [outputsRoot];
  while (stack.length > 0) {
    const cur = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(cur, { withFileTypes: true });
    } catch (_err) {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(cur, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
        continue;
      }
      if (entry.isFile() && entry.name === "graph_views.json") {
        out.push(full);
      }
    }
  }
  return out;
}

function chooseViewsJson(repoRoot) {
  const maybeProjectRoot = path.resolve(repoRoot, "..", "..");
  const searchRoots = [repoRoot, maybeProjectRoot];

  const activeCandidates = [];
  for (const root of searchRoots) {
    const activePath = path.join(root, "outputs", "runs", "active.json");
    const payload = safeReadJson(activePath);
    const graphViews = String(payload?.graph_views || "").trim();
    if (!graphViews) continue;
    const resolved = path.isAbsolute(graphViews) ? graphViews : path.resolve(root, graphViews);
    if (fs.existsSync(resolved)) activeCandidates.push(resolved);
  }
  if (activeCandidates.length > 0) return activeCandidates[0];

  const all = [];
  for (const root of searchRoots) {
    const outputsRoot = path.join(root, "outputs");
    if (!fs.existsSync(outputsRoot)) continue;
    all.push(...collectGraphViewsFiles(outputsRoot));
  }
  if (all.length === 0) return null;

  all.sort((a, b) => {
    let ta = 0;
    let tb = 0;
    try {
      ta = fs.statSync(a).mtimeMs;
      tb = fs.statSync(b).mtimeMs;
    } catch (_err) {
      ta = 0;
      tb = 0;
    }
    return tb - ta;
  });
  return all[0];
}

async function startBackendServer() {
  if (backendProc) return;

  // Check if a backend is already running on BASE_PORT or nearby ports
  for (let port = BASE_PORT; port < BASE_PORT + 5; port += 1) {
    if (await isBackendAlive(port)) {
      runtimePort = port;
      backendStartedByUs = false;
      console.log(`[desktop] Found existing backend on port ${port}, reusing it`);
      return;
    }
  }

  // No backend found — start one
  runtimePort = await pickRuntimePort(BASE_PORT);
  backendStartedByUs = true;

  if (app.isPackaged) {
    // Production: launch the bundled kn_graph.exe
    const exePath = path.join(process.resourcesPath, "kn_graph.exe");
    const args = ["serve", "--host", HOST, "--port", String(runtimePort)];
    console.log(`[desktop] backend_exe=${exePath}`);
    console.log(`[desktop] backend_port=${runtimePort}`);
    console.log(`[desktop] cmd: ${exePath} ${args.join(" ")}`);

    const installRoot = path.dirname(process.execPath);
    backendProc = spawn(exePath, args, {
      env: {
        ...process.env,
        KN_GRAPH_WORKSPACES_DIR: path.join(installRoot, "workspaces"),
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  } else {
    // Development: use uv run python
    const repoRoot = getRepoRoot();
    const args = [
      "run", "python", "-m", "kn_graph", "serve",
      "--host", HOST,
      "--port", String(runtimePort),
    ];
    if (process.env.NODE_ENV === "development" && !process.env.DISABLE_BACKEND_RELOAD) {
      args.push("--reload");
    }
    console.log(`[desktop] repoRoot=${repoRoot}`);
    console.log(`[desktop] backend_port=${runtimePort}`);
    console.log(`[desktop] cmd: uv ${args.join(" ")}`);

    backendProc = spawn("uv", args, {
      cwd: repoRoot,
      env: buildPythonEnv(repoRoot),
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  }

  backendProc.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProc.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
  backendProc.on("exit", (code, signal) => {
    const reason = signal ? `signal=${signal}` : `code=${code}`;
    console.log(`[backend] exited: ${reason}`);
    backendProc = null;
  });
}

async function waitForBackendReady() {
  const start = Date.now();
  while (Date.now() - start < START_TIMEOUT_MS) {
    if (await isBackendAlive(runtimePort)) return;
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error(`backend_start_timeout: ${healthUrl(runtimePort)}`);
}

function createMainWindow() {
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    autoHideMenuBar: true,
    title: "Scholar Wiki",
    backgroundColor: "#eef5ff",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#f7fbff",
      symbolColor: "#2c4368",
      height: 34,
    },
    backgroundMaterial: "mica",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,  // Needed for file:// protocol with crossorigin modules
    },
  });

  // In development: load from Vite dev server
  // In production: load from built files served by the backend
  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl);
  } else {
    mainWindow.loadURL(appUrl());
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.webContents.on("context-menu", (_event, params) => {
    const hasSelection = Boolean(params.selectionText && String(params.selectionText).trim());
    const menuTemplate = params.isEditable
      ? [
          { role: "undo" },
          { role: "redo" },
          { type: "separator" },
          { role: "cut" },
          { role: "copy" },
          { role: "paste" },
          { role: "selectAll" },
          { type: "separator" },
          { role: "inspect" },
        ]
      : [
          { role: "copy", enabled: hasSelection },
          { role: "selectAll" },
          { type: "separator" },
          { role: "inspect" },
        ];
    const menu = Menu.buildFromTemplate(menuTemplate);
    menu.popup({ window: mainWindow || undefined });
  });

}

function stopBackendServer() {
  if (!backendStartedByUs || !backendProc) return Promise.resolve();
  if (stoppingBackendPromise) return stoppingBackendPromise;
  const proc = backendProc;
  const pid = Number(proc.pid || 0);
  const startTs = Date.now();
  stoppingBackendPromise = new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      backendProc = null;
      const cost = Date.now() - startTs;
      console.log(`[backend] stop finished pid=${pid} cost_ms=${cost}`);
      resolve();
    };
    if (process.platform === "win32" && pid > 0) {
      execFile("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, () => {
        finish();
      });
      return;
    }
    try {
      proc.kill("SIGTERM");
    } catch (_err) {
      // ignore
    }
    const timer = setTimeout(() => {
      try {
        if (proc.exitCode === null && proc.signalCode === null) {
          proc.kill("SIGKILL");
        }
      } catch (_err) {
        // ignore
      } finally {
        finish();
      }
    }, 1800);
    proc.once("exit", () => {
      clearTimeout(timer);
      finish();
    });
  }).finally(() => {
    stoppingBackendPromise = null;
  });
  return stoppingBackendPromise;
}

// IPC handlers for renderer process
ipcMain.handle("get-backend-port", () => runtimePort);
ipcMain.handle("get-backend-url", () => `http://${HOST}:${runtimePort}`);
ipcMain.handle("restart-backend", async () => {
  await stopBackendServer();
  await startBackendServer();
  await waitForBackendReady();
  return runtimePort;
});
// Agent install: open a terminal and run a self-contained batch script.
// The script checks for Node.js first, installs via winget if missing, then npm installs the agent.
ipcMain.handle("run-in-terminal", async (_evt, packageName, binary, displayName) => {
  const pkg = String(packageName || "").trim();
  const bin = String(binary || "").trim();
  const label = String(displayName || "Agent").trim();
  if (!pkg || !bin) return { ok: false, error: "invalid_agent_info" };

  const tmpdir = require("node:os").tmpdir();
  const batPath = path.join(tmpdir, `kn_install_${bin}.bat`);

  const script = [
    "@echo off",
    "echo.",
    "echo   ╔══════════════════════════════════════════╗",
    `echo   ║   ${label} 一键安装向导              ║`,
    "echo   ╚══════════════════════════════════════════╝",
    "echo.",
    "echo   [1/2] 检查 Node.js ...",
    "echo.",
    "where node >nul 2>nul",
    "if %errorlevel% neq 0 (",
    "    echo   Node.js 未安装，正在通过 winget 安装，请稍候 ...",
    "    winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements 2>&1",
    "    echo.",
    "    REM winget installs to %%ProgramFiles%%\\nodejs, add it to PATH for this session",
    "    if exist \"%ProgramFiles%\\nodejs\\node.exe\" set \"PATH=%ProgramFiles%\\nodejs;%PATH%\"",
    "    if exist \"%SystemDrive%\\Program Files\\nodejs\\node.exe\" set \"PATH=%SystemDrive%\\Program Files\\nodejs;%PATH%\"",
    "    echo.",
    "    where node >nul 2>nul",
    "    if %errorlevel% neq 0 (",
    "        echo.",
    "        echo   ╔══════════════════════════════════════════╗",
    "        echo   ║   Node.js 安装失败                    ║",
    "        echo   ║                                      ║",
    "        echo   ║   请检查上面的 winget 报错信息。      ║",
    "        echo   ║   也可以手动去 nodejs.org 下载安装。  ║",
    "        echo   ╚══════════════════════════════════════════╝",
    "        echo.",
    "        pause",
    "        exit /b 1",
    "    )",
    "    echo   Node.js 安装成功！",
    ")",
    "echo   Node.js 版本:",
    "node --version 2>nul",
    "echo   npm 版本:",
    "npm --version 2>nul",
    "echo.",
    `echo   [2/2] 安装 ${label} ...`,
    "echo   正在下载，请耐心等待 ...",
    "echo.",
    `npm install -g ${pkg} 2>&1`,
    "set INSTALL_RESULT=%errorlevel%",
    "echo.",
    "if %INSTALL_RESULT% equ 0 (",
    "    echo.",
    "    echo   ╔══════════════════════════════════════════╗",
    "    echo   ║                                      ║",
    `    echo   ║   ${label} 安装成功！              ║`,
    "    echo   ║                                      ║",
    "    echo   ╚══════════════════════════════════════════╝",
    "    echo.",
    `    echo   版本：`,
    `    ${bin} --version 2>nul || echo   (请关闭窗口后重新打开终端验证)`,
    "    echo.",
    "    echo   可以关掉这个窗口了。",
    "    echo   回到设置页面点击【测试】按钮确认配置是否正常。",
    ") else (",
    "    echo.",
    "    echo   ╔══════════════════════════════════════════╗",
    "    echo   ║                                      ║",
    `    echo   ║   ${label} 安装失败              ║`,
    "    echo   ║                                      ║",
    "    echo   ╚══════════════════════════════════════════╝",
    "    echo.",
    "    echo   请查看上面红色报错信息，常见原因：",
    "    echo     1. 网络不通，无法访问 npm 仓库",
    "    echo     2. npm 缓存损坏（可运行 npm cache clean --force 后重试）",
    "    echo     3. 磁盘空间不足或权限不够",
    "    echo.",
    "    echo   解决问题后重新点击【安装】按钮即可。",
    ")",
    "echo.",
    "pause",
  ].join("\r\n");

  try {
    fs.writeFileSync(batPath, script, "utf-8");
    // Use cmd /K to keep window open; start to open in a new window
    execFile("cmd.exe", ["/C", `start "安装 ${label}" cmd.exe /K "${batPath}"`], { windowsHide: false });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("open-local-path", async (_evt, targetPath) => {
  const p = String(targetPath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    const err = await shell.openPath(p);
    if (err) return { ok: false, error: err };
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("read-local-file", async (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    const buf = fs.readFileSync(p);
    return { ok: true, data: buf.toString('base64'), size: buf.length };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("read-local-text", async (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    const text = fs.readFileSync(p, "utf8");
    return { ok: true, data: text, size: Buffer.byteLength(text, 'utf8') };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("write-local-text", async (_evt, filePath, text) => {
  const p = String(filePath || "").trim();
  if (!p) return { ok: false, error: "empty_path" };
  try {
    fs.writeFileSync(p, String(text ?? ""), "utf8");
    return { ok: true, size: Buffer.byteLength(String(text ?? ""), "utf8") };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

// Resolve paper file paths via backend API (called from main process)
ipcMain.handle("resolve-paper-paths", async (_evt, paperId, libraryId) => {
  const pid = encodeURIComponent(String(paperId || "").trim());
  const lib = encodeURIComponent(String(libraryId || "").trim());
  const params = lib ? `?library_id=${lib}` : "";
  const url = `http://${HOST}:${runtimePort}/paper/${pid}/files${params}`;

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(timer);
    if (!resp.ok) return { ok: false, status: resp.status };
    const payload = await resp.json();
    return { ok: true, ...payload };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("grep-workspace", async (_evt, pattern, libraryId) => {
  const pat = String(pattern || "").trim();
  if (!pat) return { ok: false, error: "empty_pattern" };
  const libId = String(libraryId || "").trim();
  const dataDir = getDefaultDataDir();
  const wsDir = path.join(dataDir, "libraries", "workspaces");

  let searchDirs = [];
  if (libId) {
    const d = path.join(wsDir, libId);
    if (fs.existsSync(d)) searchDirs = [d];
  } else {
    try {
      searchDirs = fs.readdirSync(wsDir, { withFileTypes: true })
        .filter(e => e.isDirectory())
        .map(e => path.join(wsDir, e.name));
    } catch (_e) { searchDirs = []; }
  }

  const results = [];
  const escaped = pat.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(escaped, 'gi');

  for (const dir of searchDirs) {
    const stack = [dir];
    while (stack.length > 0) {
      const cur = stack.pop();
      let entries = [];
      try { entries = fs.readdirSync(cur, { withFileTypes: true }); } catch (_e) { continue; }
      for (const entry of entries) {
        const full = path.join(cur, entry.name);
        if (entry.isDirectory()) { stack.push(full); continue; }
        if (entry.isFile() && entry.name.endsWith('.md')) {
          const text = fs.readFileSync(full, 'utf8');
          const lines = text.split('\n');
          for (let i = 0; i < lines.length; i++) {
            regex.lastIndex = 0;
            if (regex.test(lines[i])) {
              const start = Math.max(0, i - 1);
              const end = Math.min(lines.length, i + 2);
              results.push({
                filePath: full,
                fileName: entry.name,
                lineNumber: i + 1,
                snippet: lines.slice(start, end).join('\n').substring(0, 200),
              });
              break;
            }
          }
        }
      }
    }
  }

  return { ok: true, results };
});

// --- File watchers for live external-change detection ---
const fileWatchers = new Map();

ipcMain.handle("watch-file", (_evt, filePath) => {
  const p = String(filePath || "").trim();
  if (!p || !fs.existsSync(p)) return { ok: false, error: "invalid_path" };
  if (fileWatchers.has(p)) return { ok: true };

  try {
    const watcher = fs.watch(p, (eventType) => {
      if (eventType === "change") {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("file-changed", { path: p, event: "change" });
        }
      }
    });
    watcher.on("error", () => { fileWatchers.delete(p); });
    fileWatchers.set(p, watcher);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle("unwatch-file", (_evt, filePath) => {
  const p = String(filePath || "").trim();
  const watcher = fileWatchers.get(p);
  if (watcher) {
    try { watcher.close(); } catch (_e) {}
    fileWatchers.delete(p);
  }
  return { ok: true };
});

function normalizeAssetRel(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (s.startsWith("/paper/") && s.includes("/asset?")) {
    try {
      const u = new URL(s, "http://localhost");
      const qp = u.searchParams.get("rel_path");
      if (qp) return qp;
    } catch (_e) {
      return s;
    }
  }
  return s;
}

function findFirstByName(rootDir, fileName) {
  const stack = [rootDir];
  while (stack.length > 0) {
    const cur = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(cur, { withFileTypes: true });
    } catch (_e) {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(cur, entry.name);
      if (entry.isDirectory()) {
        stack.push(full);
        continue;
      }
      if (entry.isFile() && entry.name === fileName) {
        return full;
      }
    }
  }
  return "";
}

ipcMain.handle("resolve-local-asset", async (_evt, markdownPath, rawRelPath) => {
  const mdPath = String(markdownPath || "").trim();
  const relIn = normalizeAssetRel(rawRelPath);
  if (!mdPath || !relIn) return { ok: false, error: "invalid_args" };
  const rel = decodeURIComponent(relIn);
  try {
    if (path.isAbsolute(rel) && fs.existsSync(rel) && fs.statSync(rel).isFile()) {
      return { ok: true, path: rel };
    }
    const mdDir = path.dirname(mdPath);
    const direct = path.resolve(mdDir, rel);
    if (fs.existsSync(direct) && fs.statSync(direct).isFile()) {
      return { ok: true, path: direct };
    }

    const marker = `${path.sep}final_named${path.sep}`;
    const pos = mdPath.toLowerCase().indexOf(marker.toLowerCase());
    if (pos >= 0) {
      const root = mdPath.slice(0, pos);
      const stem = path.basename(mdPath, path.extname(mdPath));
      if (stem) {
        const unpackedByStem = path.resolve(root, "unpacked", stem, rel);
        if (fs.existsSync(unpackedByStem) && fs.statSync(unpackedByStem).isFile()) {
          return { ok: true, path: unpackedByStem };
        }
      }
      const fileName = path.basename(rel);
      if (fileName) {
        const unpackedRoot = path.resolve(root, "unpacked");
        if (fs.existsSync(unpackedRoot) && fs.statSync(unpackedRoot).isDirectory()) {
          const hit = findFirstByName(unpackedRoot, fileName);
          if (hit) return { ok: true, path: hit };
        }
      }
    }
    return { ok: false, error: "asset_not_found" };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

app.on("before-quit", () => {
  quitInProgress = true;
  stopBackendServer().catch(() => {});
});

app.whenReady().then(async () => {
  try {
    await startBackendServer();
    await waitForBackendReady();
    createMainWindow();
  } catch (err) {
    dialog.showErrorBox(
      "Startup Failed",
      `Failed to start backend service.\n\n${String(err)}\n\nPlease confirm uv and Python dependencies are installed.`
    );
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopBackendServer().catch(() => {}).finally(() => {
    if (process.platform !== "darwin" || quitInProgress) {
      quitInProgress = true;
      app.quit();
    }
  });
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    startBackendServer()
      .then(() => waitForBackendReady())
      .then(() => createMainWindow())
      .catch((err) => {
        dialog.showErrorBox(
          "Startup Failed",
          `Failed to start backend service.\n\n${String(err)}\n\nPlease confirm uv and Python dependencies are installed.`
        );
      });
  }
});

