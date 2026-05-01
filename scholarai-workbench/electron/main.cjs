const { app, BrowserWindow, Menu, dialog, ipcMain } = require("electron");
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
  return `http://${HOST}:${runtimePort}/frontend/workbench/`;
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
  const weaviateUrl = process.env.WEAVIATE_URL || "http://127.0.0.1:8090";
  return { ...process.env, PYTHONPATH: pythonPath, KN_GRAPH_DATA_DIR: dataDir, WEAVIATE_URL: weaviateUrl };
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
  const viewsJson = chooseViewsJson(repoRoot);

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

  if (viewsJson) {
    args.push("--views-json", viewsJson);
  }
  args.push("--allow-non-supply-chain");

  console.log(`[desktop] repoRoot=${repoRoot}`);
  console.log(`[desktop] backend_port=${runtimePort}`);
  console.log(`[desktop] views_json=${viewsJson}`);
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

  // Open devtools in development
  if (process.env.NODE_ENV === "development") {
    mainWindow.webContents.openDevTools();
  }
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

app.on("before-quit", () => {
  quitInProgress = true;
  stopBackendServer().catch(() => {});
});

async function startWeaviate() {
  const weaviateUrl = process.env.WEAVIATE_URL || "http://127.0.0.1:8090";

  try {
    const resp = await fetch(`${weaviateUrl}/v1/.well-known/ready`, { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      console.log(`[desktop] Weaviate already running at ${weaviateUrl}`);
      return true;
    }
  } catch (_) { /* not running, try to start */ }

  try {
    const dockerCheck = await execFileAsync("docker", ["--version"], { timeout: 5000, windowsHide: true });
    console.log(`[desktop] Docker available: ${dockerCheck.stdout.trim()}`);
  } catch (_) {
    console.log("[desktop] Docker not available, skipping Weaviate startup");
    return false;
  }

  try {
    const ps = await execFileAsync("docker", ["ps", "-q", "-f", "name=kn-graph-weaviate"], { timeout: 5000, windowsHide: true });
    if (ps.stdout.trim()) {
      console.log("[desktop] Weaviate container already running");
    } else {
      const composeFile = path.resolve(getRepoRoot(), "docker-compose.weaviate.yml");
      if (fs.existsSync(composeFile)) {
        console.log(`[desktop] Starting Weaviate via docker compose...`);
        await execFileAsync("docker", ["compose", "-f", composeFile, "up", "-d"], { timeout: 30000, windowsHide: true });
      } else {
        console.log(`[desktop] docker-compose.weaviate.yml not found at ${composeFile}, using docker run`);
        await execFileAsync("docker", [
          "run", "-d", "--name", "kn-graph-weaviate",
          "-p", "8090:8080",
          "-e", "QUERY_DEFAULTS_LIMIT=100",
          "-e", "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true",
          "-v", "kn-graph-weaviate-data:/var/lib/weaviate",
          "--restart", "unless-stopped",
          "cr.weaviate.io/semitechnologies/weaviate:1.28.4"
        ], { timeout: 60000, windowsHide: true });
      }
    }
  } catch (err) {
    console.log(`[desktop] Docker Weaviate start failed: ${err.message}`);
    return false;
  }

  const startTime = Date.now();
  while (Date.now() - startTime < 30000) {
    try {
      const resp = await fetch(`${weaviateUrl}/v1/.well-known/ready`, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) {
        console.log(`[desktop] Weaviate ready at ${weaviateUrl}`);
        return true;
      }
    } catch (_) { /* not ready yet */ }
    await new Promise(r => setTimeout(r, 1000));
  }
  console.log("[desktop] Weaviate health check timed out, continuing without vector search");
  return false;
}

app.whenReady().then(async () => {
  try {
    await startBackendServer();
    await waitForBackendReady();
    await startWeaviate();
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
