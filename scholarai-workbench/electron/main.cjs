const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const { spawn, execFile, execFileSync } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { promisify } = require("node:util");
const execFileAsync = promisify(execFile);

const HOST = "127.0.0.1";
// Dev uses the project backend port; packaged app defaults to 8014 to avoid cross-connecting.
const BASE_PORT = Number(process.env.KN_GRAPH_PORT || (app.isPackaged ? 8014 : 8013));
const DEV_DATA_DIR_WIN = "D:\\AppData\\KNGraphApp-dev";
const START_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 800;
const MAX_PORT_SCAN = 20;
const DESKTOP_CONFIG_NAME = "desktop_config.json";

let backendProc = null;
let mainWindow = null;
let runtimePort = BASE_PORT;
let stoppingBackendPromise = null;
let quitInProgress = false;
let backendStartedByUs = false;
const singleInstanceLock = app.requestSingleInstanceLock();

if (!singleInstanceLock) {
  app.quit();
}

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

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

function getDefaultDataDir(opts = {}) {
  const ignoreEnv = Boolean(opts && opts.ignoreEnv);
  const envDir = ignoreEnv ? "" : String(process.env.KN_GRAPH_DATA_DIR || "").trim();
  if (envDir) return envDir;
  const cfg = readDesktopConfig();
  const cfgDir = String(cfg.data_dir || "").trim();
  if (cfgDir) return cfgDir;
  if (app.isPackaged) {
    // Packaged app data must live in a user-writable directory.
    return path.join(app.getPath("userData"), "data");
  }
  if (process.platform === "win32") {
    // Dev data directory is fixed to avoid any mix-up with packaged data.
    return DEV_DATA_DIR_WIN;
  }
  return path.join(process.env.HOME || process.env.USERPROFILE || ".", ".kn_graph-dev");
}

function buildPythonEnv(repoRoot) {
  const prev = String(process.env.PYTHONPATH || "").trim();
  const sep = process.platform === "win32" ? ";" : ":";
  const pythonPath = prev ? `${repoRoot}${sep}${prev}` : repoRoot;
  const dataDir = getDefaultDataDir();
  const workspacesDir = path.join(dataDir, "libraries", "workspaces");
  return {
    ...process.env,
    PYTHONPATH: pythonPath,
    KN_GRAPH_DATA_DIR: dataDir,
    KN_GRAPH_WORKSPACES_DIR: workspacesDir,
    LITERATURE_LIBRARY_WORKSPACES_ROOT: workspacesDir,
  };
}

function desktopConfigPath() {
  return path.join(app.getPath("userData"), DESKTOP_CONFIG_NAME);
}

function readDesktopConfig() {
  try {
    const p = desktopConfigPath();
    if (!fs.existsSync(p)) return {};
    const raw = fs.readFileSync(p, "utf8");
    const obj = JSON.parse(raw);
    return obj && typeof obj === "object" ? obj : {};
  } catch (_err) {
    return {};
  }
}

function writeDesktopConfig(nextCfg) {
  const current = readDesktopConfig();
  const merged = { ...current, ...(nextCfg || {}) };
  const p = desktopConfigPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(merged, null, 2), "utf8");
  return merged;
}

function migrateDirectoryContents(srcDir, dstDir) {
  const src = path.resolve(String(srcDir || "").trim());
  const dst = path.resolve(String(dstDir || "").trim());
  if (!src || !dst) throw new Error("invalid_migrate_path");
  if (src.toLowerCase() === dst.toLowerCase()) return { moved: 0 };
  if (!fs.existsSync(src) || !fs.statSync(src).isDirectory()) return { moved: 0 };

  fs.mkdirSync(dst, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });
  if (entries.length === 0) return { moved: 0 };

  const copiedTargets = [];
  try {
    for (const entry of entries) {
      const from = path.join(src, entry.name);
      const to = path.join(dst, entry.name);
      if (fs.existsSync(to)) {
        throw new Error(`target_conflict:${to}`);
      }
      fs.cpSync(from, to, { recursive: true, force: false, errorOnExist: true });
      copiedTargets.push(to);
    }
  } catch (e) {
    for (let i = copiedTargets.length - 1; i >= 0; i -= 1) {
      try {
        fs.rmSync(copiedTargets[i], { recursive: true, force: true });
      } catch (_rollbackErr) {
        // ignore rollback error
      }
    }
    throw e;
  }

  for (const entry of entries) {
    const from = path.join(src, entry.name);
    fs.rmSync(from, { recursive: true, force: true });
  }
  return { moved: entries.length };
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

  // Development-only reuse: avoid connecting packaged app to a stray dev backend.
  if (!app.isPackaged) {
    // Check if a backend is already running on BASE_PORT or nearby ports
    for (let port = BASE_PORT; port < BASE_PORT + 5; port += 1) {
      if (await isBackendAlive(port)) {
        runtimePort = port;
        backendStartedByUs = false;
        console.log(`[desktop] Found existing backend on port ${port}, reusing it`);
        return;
      }
    }
  }

  // No backend found — start one
  runtimePort = await pickRuntimePort(BASE_PORT);
  backendStartedByUs = true;

  if (app.isPackaged) {
    // Production: launch the bundled kn_graph.exe
    const exePath = path.join(process.resourcesPath, "kn_graph.exe");
    const args = ["serve", "--host", HOST, "--port", String(runtimePort)];
    const dataDir = getDefaultDataDir({ ignoreEnv: true });
    args.push("--data-dir", dataDir);
    console.log(`[desktop] backend_exe=${exePath}`);
    console.log(`[desktop] backend_port=${runtimePort}`);
    console.log(`[desktop] backend_data_dir=${dataDir}`);
    console.log(`[desktop] cmd: ${exePath} ${args.join(" ")}`);

    const workspacesDir = path.join(dataDir, "libraries", "workspaces");
    backendProc = spawn(exePath, args, {
      env: {
        ...process.env,
        KN_GRAPH_DATA_DIR: dataDir,
        KN_GRAPH_WORKSPACES_DIR: workspacesDir,
        LITERATURE_LIBRARY_WORKSPACES_ROOT: workspacesDir,
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
  } else {
    // Development: use uv run python
    const repoRoot = getRepoRoot();
    const dataDir = getDefaultDataDir();
    const args = [
      "run", "python", "-m", "kn_graph", "serve",
      "--host", HOST,
      "--port", String(runtimePort),
      "--data-dir", dataDir,
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
ipcMain.handle("agent-precheck", async (_evt, binary) => {
  const state = await detectNodeAndAgent(binary);
  return { ok: true, stage: "precheck", ...state };
});
ipcMain.handle("get-data-dir", () => ({ ok: true, data_dir: getDefaultDataDir() }));
ipcMain.handle("set-data-dir", async (_evt, value) => {
  const next = String(value || "").trim();
  if (!next) return { ok: false, error: "data_dir_required" };
  try {
    const prev = getDefaultDataDir();
    fs.mkdirSync(next, { recursive: true });
    const migration = migrateDirectoryContents(prev, next);
    writeDesktopConfig({ data_dir: next });
    return {
      ok: true,
      data_dir: next,
      restart_required: true,
      migrated: true,
      migrated_entries: migration.moved,
    };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});
ipcMain.handle("get-backend-url", () => `http://${HOST}:${runtimePort}`);
ipcMain.on("get-backend-url-sync", (event) => {
  event.returnValue = `http://${HOST}:${runtimePort}`;
});
ipcMain.handle("restart-backend", async () => {
  await stopBackendServer();
  await startBackendServer();
  await waitForBackendReady();
  return runtimePort;
});
function isAllowedInstallCommand(command) {
  const normalized = String(command || "").trim().replace(/\s+/g, " ");
  if (normalized === "winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements") return true;
  return /^npm install -g (@?[a-z0-9._-]+\/)?[a-z0-9._-]+(@[a-z0-9._-]+)?$/i.test(normalized);
}

ipcMain.handle("run-terminal-command", async (_evt, label, command) => {
  const safeLabel = String(label || "Install").replace(/[^\w .@-]/g, "").trim() || "Install";
  const rawCommand = String(command || "").trim().replace(/\s+/g, " ");
  if (!rawCommand) return { ok: false, error: "empty_command" };
  if (!isAllowedInstallCommand(rawCommand)) return { ok: false, error: "install_command_not_allowed" };

  try {
    const child = spawn("cmd.exe", ["/c", "start", safeLabel, "cmd.exe", "/K", rawCommand], {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.unref();
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

function firstExistingPath(candidates) {
  for (const p of candidates || []) {
    const cur = String(p || "").trim();
    if (!cur) continue;
    try {
      if (fs.existsSync(cur)) return cur;
    } catch (_err) {
      // ignore
    }
  }
  return "";
}

function whereFirst(commandName) {
  const name = String(commandName || "").trim();
  if (!name || /[\\/:*?"<>|]/.test(name)) return "";
  try {
    const whereOut = execFileSync("where", [name], {
      windowsHide: true,
      encoding: "utf8",
      timeout: 8000,
      maxBuffer: 1024 * 1024,
    });
    const hit = String(whereOut || "").split(/\r?\n/).map((s) => s.trim()).find(Boolean);
    if (hit && fs.existsSync(hit)) return hit;
  } catch (_err) {
    // ignore
  }
  return "";
}

function resolveNodeExe() {
  const pf = String(process.env.ProgramFiles || "").trim();
  const pf86 = String(process.env["ProgramFiles(x86)"] || "").trim();
  const lad = String(process.env.LocalAppData || "").trim();
  return firstExistingPath([
    pf ? path.join(pf, "nodejs", "node.exe") : "",
    pf86 ? path.join(pf86, "nodejs", "node.exe") : "",
    lad ? path.join(lad, "Programs", "nodejs", "node.exe") : "",
  ]) || whereFirst("node.exe") || whereFirst("node");
}

function resolveNpmCmd(nodeExePath = "") {
  const nodeExe = String(nodeExePath || "").trim();
  const nodeDir = nodeExe ? path.dirname(nodeExe) : "";
  const pf = String(process.env.ProgramFiles || "").trim();
  const pf86 = String(process.env["ProgramFiles(x86)"] || "").trim();
  return firstExistingPath([
    nodeDir ? path.join(nodeDir, "npm.cmd") : "",
    pf ? path.join(pf, "nodejs", "npm.cmd") : "",
    pf86 ? path.join(pf86, "nodejs", "npm.cmd") : "",
  ]) || whereFirst("npm.cmd") || whereFirst("npm");
}

function resolveAgentCmd(binary) {
  const bin = String(binary || "").trim();
  if (!bin || /[\\/:*?"<>|]/.test(bin)) return "";
  const cmdName = bin.toLowerCase().endsWith(".cmd") ? bin : `${bin}.cmd`;
  const appData = String(process.env.APPDATA || "").trim();
  return firstExistingPath([appData ? path.join(appData, "npm", cmdName) : ""]) || whereFirst(cmdName) || whereFirst(bin);
}

async function runExecFile(file, args, opts = {}) {
  const timeoutMs = Number(opts.timeoutMs || 10 * 60 * 1000);
  const cwd = String(opts.cwd || process.cwd());
  const env = opts.env || process.env;
  try {
    const out = await execFileAsync(file, args, {
      cwd,
      env,
      windowsHide: true,
      timeout: timeoutMs,
      maxBuffer: 20 * 1024 * 1024,
    });
    return {
      ok: true,
      code: 0,
      stdout: String(out.stdout || ""),
      stderr: String(out.stderr || ""),
    };
  } catch (e) {
    return {
      ok: false,
      code: Number(e?.code ?? -1),
      stdout: String(e?.stdout || ""),
      stderr: String(e?.stderr || e?.message || ""),
    };
  }
}

async function detectNodeAndAgent(binary) {
  const nodeExe = resolveNodeExe();
  const npmCmd = resolveNpmCmd(nodeExe);
  const agentCmd = resolveAgentCmd(binary);
  let nodeVersion = "";
  let npmVersion = "";
  let agentVersion = "";
  if (nodeExe) {
    const n = await runExecFile(nodeExe, ["--version"], { timeoutMs: 20_000 });
    nodeVersion = String((n.stdout || n.stderr || "").trim().split(/\r?\n/)[0] || "");
  }
  if (npmCmd) {
    const n = await runExecFile(npmCmd, ["--version"], { timeoutMs: 20_000 });
    npmVersion = String((n.stdout || n.stderr || "").trim().split(/\r?\n/)[0] || "");
  }
  if (agentCmd) {
    const c = await runExecFile(agentCmd, ["--version"], { timeoutMs: 20_000 });
    agentVersion = String((c.stdout || c.stderr || "").trim().split(/\r?\n/)[0] || "");
  }
  return {
    node: { installed: Boolean(nodeExe), path: nodeExe, version: nodeVersion },
    npm: { installed: Boolean(npmCmd), path: npmCmd, version: npmVersion },
    agent: { installed: Boolean(agentCmd), path: agentCmd, version: agentVersion },
  };
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
    const hint = app.isPackaged
      ? "Please check installation integrity and write permissions for the app data directory."
      : "Please confirm uv and Python dependencies are installed.";
    dialog.showErrorBox(
      "Startup Failed",
      `Failed to start backend service.\n\n${String(err)}\n\n${hint}`
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
        const hint = app.isPackaged
          ? "Please check installation integrity and write permissions for the app data directory."
          : "Please confirm uv and Python dependencies are installed.";
        dialog.showErrorBox(
          "Startup Failed",
          `Failed to start backend service.\n\n${String(err)}\n\n${hint}`
        );
      });
  }
});

