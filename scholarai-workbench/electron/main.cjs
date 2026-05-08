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

function buildPythonEnv(repoRoot) {
  const prev = String(process.env.PYTHONPATH || "").trim();
  const sep = process.platform === "win32" ? ";" : ":";
  const pythonPath = prev ? `${repoRoot}${sep}${prev}` : repoRoot;
  const dataDir = process.env.KN_GRAPH_DATA_DIR || (process.platform === "win32" ? "D:\\KNGraphApp" : path.join(process.env.HOME || process.env.USERPROFILE || ".", ".kn_graph"));
  return { ...process.env, PYTHONPATH: pythonPath, KN_GRAPH_DATA_DIR: dataDir };
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
  const repoRoot = getRepoRoot();

  const args = [
    "run",
    "python",
    "-m",
    "kn_graph",
    "serve",
    "--host",
    HOST,
    "--port",
    String(runtimePort),
  ];
  // In development, enable backend hot-reload
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
    title: "KN Graph Workbench",
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

  // Always open devtools for reader diagnostics in current development workflow.
  mainWindow.webContents.openDevTools({ mode: "detach" });
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

// Read paper file content given file paths payload
ipcMain.handle("resolve-paper-file", async (_evt, filesPayload) => {
  const files = filesPayload?.files || {};
  const order = ["markdown", "pdf", "html"];
  for (const key of order) {
    const f = files[key];
    if (!f?.path) continue;
    const p = String(f.path).trim();
    if (!p || !fs.existsSync(p) || !fs.statSync(p).isFile()) continue;
    const name = path.basename(p);
    if (key === "pdf") {
      const buf = fs.readFileSync(p);
      return { ok: true, type: "pdf", path: p, name, data: buf.toString("base64"), size: buf.length };
    }
    const text = fs.readFileSync(p, "utf8");
    return { ok: true, type: key, path: p, name, data: text, size: Buffer.byteLength(text, "utf8") };
  }
  return { ok: false, error: "no_readable_file" };
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

