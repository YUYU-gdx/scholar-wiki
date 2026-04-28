const { app, BrowserWindow, Menu, dialog } = require("electron");
const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

const HOST = "127.0.0.1";
const BASE_PORT = Number(process.env.KN_GRAPH_PORT || 8013);
const ASYNC_BASE_PORT = Number(process.env.KN_ASYNC_PIPELINE_PORT || 8021);
const START_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 800;
const MAX_PORT_SCAN = 20;

let backendProc = null;
let asyncBackendProc = null;
let mainWindow = null;
let runtimePort = BASE_PORT;
let runtimeAsyncPort = ASYNC_BASE_PORT;
let stoppingBackendPromise = null;
let stoppingAsyncPromise = null;
let quitInProgress = false;

function workbenchUrl() {
  return `http://${HOST}:${runtimePort}/frontend/workbench/?async_port=${encodeURIComponent(String(runtimeAsyncPort))}`;
}

function healthUrl() {
  return `http://${HOST}:${runtimePort}/graph/overview`;
}

function asyncHealthUrl() {
  return `http://${HOST}:${runtimeAsyncPort}/healthz`;
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

async function pickRuntimePort(base, excluded = []) {
  const blocked = new Set(excluded);
  for (let i = 0; i <= MAX_PORT_SCAN; i += 1) {
    const candidate = base + i;
    if (blocked.has(candidate)) continue;
    // eslint-disable-next-line no-await-in-loop
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
  return { ...process.env, PYTHONPATH: pythonPath };
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
  if (activeCandidates.length > 0) {
    return activeCandidates[0];
  }

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
  runtimePort = await pickRuntimePort(BASE_PORT, [runtimeAsyncPort]);
  const repoRoot = getRepoRoot();
  const viewsJson = chooseViewsJson(repoRoot);
  if (!viewsJson) {
    throw new Error("missing_graph_views_json: no usable outputs/**/graph_views.json found");
  }
  const args = [
    "run",
    "python",
    "scripts/smj_pipeline/serve_graph_api.py",
    "--host",
    HOST,
    "--port",
    String(runtimePort),
    "--views-json",
    viewsJson,
    "--allow-non-supply-chain",
  ];
  console.log(`[desktop] repoRoot=${repoRoot}`);
  console.log(`[desktop] backend_port=${runtimePort}`);
  console.log(`[desktop] views_json=${viewsJson}`);
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
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      const resp = await fetch(healthUrl(), { signal: controller.signal });
      clearTimeout(timer);
      if (resp.ok) return;
    } catch (_err) {
      // Retry until timeout.
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error(`backend_start_timeout: ${healthUrl()}`);
}

async function startAsyncBackendServer() {
  if (asyncBackendProc) return;
  runtimeAsyncPort = await pickRuntimePort(ASYNC_BASE_PORT, []);
  const repoRoot = getRepoRoot();
  const args = [
    "run",
    "python",
    "scripts/smj_pipeline/serve_async_pipeline_api.py",
    "--host",
    HOST,
    "--port",
    String(runtimeAsyncPort),
  ];
  console.log(`[desktop] async_port=${runtimeAsyncPort}`);
  asyncBackendProc = spawn("uv", args, {
    cwd: repoRoot,
    env: buildPythonEnv(repoRoot),
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  asyncBackendProc.stdout.on("data", (chunk) => {
    process.stdout.write(`[async-backend] ${chunk}`);
  });
  asyncBackendProc.stderr.on("data", (chunk) => {
    process.stderr.write(`[async-backend] ${chunk}`);
  });
  asyncBackendProc.on("exit", (code, signal) => {
    const reason = signal ? `signal=${signal}` : `code=${code}`;
    console.log(`[async-backend] exited: ${reason}`);
    asyncBackendProc = null;
  });
}

async function waitForAsyncBackendReady() {
  const start = Date.now();
  while (Date.now() - start < START_TIMEOUT_MS) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      const resp = await fetch(asyncHealthUrl(), { signal: controller.signal });
      clearTimeout(timer);
      if (resp.ok) return;
    } catch (_err) {
      // Retry until timeout.
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new Error(`async_backend_start_timeout: ${asyncHealthUrl()}`);
}

function createMainWindow() {
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    autoHideMenuBar: true,
    title: "KN Graph Desktop",
    backgroundColor: "#eef5ff",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#f7fbff",
      symbolColor: "#2c4368",
      height: 34,
    },
    backgroundMaterial: "mica",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(workbenchUrl());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function stopBackendServer() {
  if (!backendProc) return Promise.resolve();
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

function stopAsyncBackendServer() {
  if (!asyncBackendProc) return Promise.resolve();
  if (stoppingAsyncPromise) return stoppingAsyncPromise;
  const proc = asyncBackendProc;
  const pid = Number(proc.pid || 0);
  const startTs = Date.now();
  stoppingAsyncPromise = new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      asyncBackendProc = null;
      const cost = Date.now() - startTs;
      console.log(`[async-backend] stop finished pid=${pid} cost_ms=${cost}`);
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
    stoppingAsyncPromise = null;
  });
  return stoppingAsyncPromise;
}

app.on("before-quit", () => {
  quitInProgress = true;
  stopBackendServer().catch(() => {});
  stopAsyncBackendServer().catch(() => {});
});

app.whenReady().then(async () => {
  try {
    await startAsyncBackendServer();
    await waitForAsyncBackendReady();
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
  Promise.all([stopBackendServer().catch(() => {}), stopAsyncBackendServer().catch(() => {})])
    .finally(() => {
      if (process.platform !== "darwin" || quitInProgress) {
        quitInProgress = true;
        app.quit();
      }
    });
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    startAsyncBackendServer()
      .then(() => waitForAsyncBackendReady())
      .then(() => startBackendServer())
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
