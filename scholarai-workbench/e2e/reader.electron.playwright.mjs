import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { _electron as electron } from 'playwright';

const repoRoot = path.resolve(process.cwd(), '..');
const workbenchDir = process.cwd();
const baseUrl = 'http://127.0.0.1:3000';
const tmpDir = path.join(repoRoot, '.tmp', 'electron-reader-e2e');
fs.mkdirSync(tmpDir, { recursive: true });

function isPortOpen(host, port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(500);
    socket.on('connect', () => { socket.destroy(); resolve(true); });
    socket.on('timeout', () => { socket.destroy(); resolve(false); });
    socket.on('error', () => resolve(false));
    socket.connect(port, host);
  });
}

async function waitPort(host, port, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isPortOpen(host, port)) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`timeout waiting for ${host}:${port}`);
}

function writeFixtureFiles() {
  const files = {
    md1: path.join(tmpDir, 'p1.md'),
    html1: path.join(tmpDir, 'p1.html'),
    html2: path.join(tmpDir, 'p2.html'),
    raw: path.join(tmpDir, 'raw.md'),
  };
  fs.writeFileSync(files.md1, 'MD_ONE_CONTENT', 'utf8');
  fs.writeFileSync(files.html1, '<div id="html-one">HTML_ONE_CONTENT</div>', 'utf8');
  fs.writeFileSync(files.html2, '<img src=x onerror="window.__xss_flag=\'TRIGGERED\'" /><div id="html-two">HTML_TWO_CONTENT</div>', 'utf8');
  fs.writeFileSync(files.raw, 'RAW_FALLBACK_OK', 'utf8');
  return files;
}

async function mountMockRoutes(window, files) {
  await window.route('**/*', async (route) => {
    const url = route.request().url();
    if (url.includes('/literature/libraries')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          libraries: [{ library_id: 'supply_chain', paper_count: 2, updated_at: '2026-05-03T00:00:00Z', path: 'D:/mock' }],
          default_library_id: 'supply_chain',
        }),
      });
    }
    if (url.includes('/chat/sessions')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sessions: [] }) });
    }
    if (url.includes('/graph/full')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          meta: { library_id: 'supply_chain', paper_count: 2, node_count: 0, edge_count: 0 },
          nodes: [],
          edges: [],
          moderation_links: [],
          interaction_links: [],
          isolated_nodes: [],
          paper_map: {
            'supply_chain::paper-key-1': {
              paper_id: 'paper-key-1',
              library_id: 'supply_chain',
              title: 'paper-key-1',
            },
            'supply_chain::paper-key-2': {
              paper_id: 'paper-key-2',
              library_id: 'supply_chain',
              title: 'paper-key-2',
            },
          },
        }),
      });
    }

    const m = /\/paper\/([^/]+)\/files/.exec(url);
    if (m) {
      const pid = decodeURIComponent(m[1]);
      if (pid === 'paper-key-1') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            paper_id: 'paper-key-1',
            library_id: 'supply_chain',
            files: {
              markdown: { path: files.md1, name: 'p1.md', size_bytes: fs.statSync(files.md1).size },
              html: { path: files.html1, name: 'p1.html', size_bytes: fs.statSync(files.html1).size },
            },
            default_view: 'markdown',
          }),
        });
      }
      if (pid === 'paper-key-2') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            paper_id: 'paper-key-2',
            library_id: 'supply_chain',
            files: { html: { path: files.html2, name: 'p2.html', size_bytes: fs.statSync(files.html2).size } },
            default_view: 'html',
          }),
        });
      }
      if (pid === 'paper-404') {
        return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'not_found' }) });
      }
      if (pid === 'paper-500') {
        return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'server_error' }) });
      }
      if (pid === 'raw-ok') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            paper_id: 'raw-ok',
            library_id: 'supply_chain',
            files: { markdown: { path: files.raw, name: 'raw.md', size_bytes: fs.statSync(files.raw).size } },
            default_view: 'markdown',
          }),
        });
      }
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'not_found' }) });
    }

    return route.continue();
  });
}

async function openReader(window, paperId, preferredType, rawPaperId = '') {
  await window.evaluate(({ paperId, preferredType, rawPaperId }) => {
    window.postMessage({
      type: 'KN_GRAPH_OPEN_READER',
      payload: { paperId, libraryId: 'supply_chain', preferredType, rawPaperId },
    }, '*');
  }, { paperId, preferredType, rawPaperId });
  await window.waitForTimeout(1200);
}

async function bodyText(window) {
  return await window.locator('body').innerText();
}

async function run() {
  const files = writeFixtureFiles();

  let viteProc = null;
  const viteAlreadyRunning = await isPortOpen('127.0.0.1', 3000);
  if (!viteAlreadyRunning) {
    viteProc = spawn('npm.cmd', ['run', 'dev'], {
      cwd: workbenchDir,
      stdio: 'ignore',
      windowsHide: true,
      shell: false,
    });
    await waitPort('127.0.0.1', 3000, 60000);
  }

  let app;
  try {
    app = await electron.launch({
      cwd: workbenchDir,
      args: ['.'],
      env: {
        ...process.env,
        NODE_ENV: 'test',
        VITE_DEV_SERVER_URL: baseUrl,
      },
    });

    const window = await app.firstWindow();
    await mountMockRoutes(window, files);
    await window.reload({ waitUntil: 'networkidle' });

    // 0) library buttons should reflect /paper/{id}/files by file position (not filename)
    await window.getByRole('button', { name: 'Library' }).click();
    await window.getByText('paper-key-1').first().waitFor({ state: 'visible', timeout: 30000 });
    const paper1Card = window.locator('div.p-4').filter({ hasText: 'paper-key-1' }).first();
    const paper2Card = window.locator('div.p-4').filter({ hasText: 'paper-key-2' }).first();
    await paper1Card.getByRole('button', { name: 'MD' }).waitFor({ state: 'visible' });
    assert.ok(await paper1Card.getByRole('button', { name: 'MD' }).isVisible());
    assert.ok(await paper1Card.getByRole('button', { name: 'HTML' }).isVisible());
    assert.equal(await paper1Card.getByRole('button', { name: 'PDF' }).count(), 0);
    assert.ok(await paper2Card.getByRole('button', { name: 'HTML' }).isVisible());
    assert.equal(await paper2Card.getByRole('button', { name: 'MD' }).count(), 0);

    await window.getByRole('button', { name: 'Graph' }).click();
    await window.waitForTimeout(600);

    // 1) same paper different preferred type
    await openReader(window, 'paper-key-1', 'markdown', 'raw-1');
    let text = await bodyText(window);
    assert.ok(text.includes('MD_ONE_CONTENT'));
    assert.ok(!text.includes('HTML_ONE_CONTENT'));

    await window.getByRole('button', { name: 'Back' }).click();
    await window.waitForTimeout(500);

    await openReader(window, 'paper-key-1', 'html', 'raw-1');
    text = await bodyText(window);
    assert.ok(text.includes('HTML_ONE_CONTENT'));
    assert.ok(!text.includes('MD_ONE_CONTENT'));

    // 2) html should not execute inline handlers
    await window.getByRole('button', { name: 'Back' }).click();
    await window.waitForTimeout(500);

    await openReader(window, 'paper-key-2', 'html');
    text = await bodyText(window);
    assert.ok(text.includes('HTML_TWO_CONTENT'));
    const xssFlag = await window.evaluate(() => window.__xss_flag || '');
    assert.equal(xssFlag, '', 'inline handler executed unexpectedly');

    // 3) fallback on 404 should work
    await window.getByRole('button', { name: 'Back' }).click();
    await window.waitForTimeout(500);

    await openReader(window, 'paper-404', 'markdown', 'raw-ok');
    text = await bodyText(window);
    assert.ok(text.includes('RAW_FALLBACK_OK'));

    // 4) fallback on 500 should NOT happen
    await window.getByRole('button', { name: 'Back' }).click();
    await window.waitForTimeout(500);

    await openReader(window, 'paper-500', 'markdown', 'raw-ok');
    text = await bodyText(window);
    assert.ok(text.includes('failed to resolve paper files: 500'));
    assert.ok(!text.includes('RAW_FALLBACK_OK'));

    console.log('electron reader e2e passed');
  } finally {
    if (app) {
      await app.close();
    }
    if (viteProc) {
      viteProc.kill('SIGTERM');
    }
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
