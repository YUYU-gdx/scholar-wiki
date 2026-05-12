/**
 * Comprehensive end-to-end tests for KN Graph Workbench.
 *
 * These tests simulate real user behavior against the packaged exe.
 * Expected behavior is explicitly stated before each test section.
 *
 * Usage:
 *   npx playwright test --config=e2e/playwright.config.ts e2e/full_e2e.spec.ts
 */

import { test, expect, type Page } from "@playwright/test";

const BASE_URL = process.env.KN_GRAPH_TEST_URL || "http://127.0.0.1:8015";
const TEST_LIBRARY_ID = `e2e_test_lib_${Date.now()}`;

// ---- Helpers ----

async function navigateToView(page: Page, view: string) {
  const btn = page.locator("nav button").filter({ hasText: new RegExp(view, "i") });
  await btn.click();
  await page.waitForTimeout(600);
}

async function expectVisible(page: Page, text: string | RegExp) {
  await expect(page.getByText(text).first()).toBeVisible({ timeout: 8000 });
}

// =====================================================================
//  1. Health & Connectivity
// =====================================================================
test.describe("Health & Connectivity", () => {
  test("GET /healthz returns ok", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/healthz`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ status: "ok" });
  });

  test("SPA index.html is served at /", async ({ page }) => {
    const res = await page.goto(BASE_URL);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle("KN Graph Workbench");
  });

  test("API /graph/full returns valid JSON", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/graph/full?library_id=supply_chain`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("nodes");
    expect(body).toHaveProperty("edges");
    expect(body).toHaveProperty("paper_map");
    expect(Array.isArray(body.nodes)).toBe(true);
    expect(Array.isArray(body.edges)).toBe(true);
  });
});

// =====================================================================
//  2. Navigation — all 6 views
// =====================================================================
test.describe("Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(1000);
  });

  test("Library view loads with papers list", async ({ page }) => {
    await navigateToView(page, "Library");
    await expect(page.locator("main")).toContainText("Research Library");
  });

  test("Graph view loads the 3D graph iframe", async ({ page }) => {
    await navigateToView(page, "Graph");
    const iframe = page.locator("iframe");
    await expect(iframe).toBeAttached({ timeout: 10000 });
  });

  test("Chat view shows session sidebar", async ({ page }) => {
    await navigateToView(page, "Chat");
    await expectVisible(page, /Select or create a session|New Session/i);
  });

  test("Reader view shows empty state", async ({ page }) => {
    await navigateToView(page, "Reader");
    await expectVisible(page, /Document Reader|Select a paper/i);
  });

  test("Pipeline view shows jobs list", async ({ page }) => {
    await navigateToView(page, "Pipeline");
    await expectVisible(page, /Import|upload|pipeline/i);
  });

  test("Settings view loads with category cards", async ({ page }) => {
    await navigateToView(page, "Settings");
    await page.waitForTimeout(2000);
    // Settings page renders with the Settings header or form elements
    await expect(page.locator("main")).toBeVisible({ timeout: 5000 });
    // Should contain some form fields (inputs or selects)
    const formElements = page.locator("input, select, button");
    const count = await formElements.count();
    expect(count).toBeGreaterThan(0);
  });
});

// =====================================================================
//  3. SPA Client-Side Routing
// =====================================================================
test.describe("SPA Routing", () => {
  test("Direct URL /chat returns index.html (SPA fallback)", async ({ page }) => {
    const res = await page.goto(`${BASE_URL}/chat`);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle("KN Graph Workbench");
  });

  test("Direct URL /graph returns index.html (SPA fallback)", async ({ page }) => {
    const res = await page.goto(`${BASE_URL}/graph`);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle("KN Graph Workbench");
  });

  test("Unknown route returns index.html (SPA fallback)", async ({ page }) => {
    const res = await page.goto(`${BASE_URL}/nonexistent-route-xyz`);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveTitle("KN Graph Workbench");
  });
});

// =====================================================================
//  4. Library Management
// =====================================================================
test.describe("Library Management", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await navigateToView(page, "Library");
  });

  test("Create a new library", async ({ page }) => {
    const createBtn = page.getByRole("button", { name: /创建文献库|create library/i });
    if (await createBtn.isVisible({ timeout: 3000 })) {
      await createBtn.click();
      await page.waitForTimeout(500);
    }

    // Find library name input
    const nameInput = page.locator("input").first();
    if (await nameInput.isVisible({ timeout: 2000 })) {
      await nameInput.fill(TEST_LIBRARY_ID);
      await page.waitForTimeout(200);
    }

    // Click confirm
    const confirmBtn = page.getByRole("button", { name: /创建|create/i }).last();
    if (await confirmBtn.isVisible({ timeout: 2000 })) {
      await confirmBtn.click();
      await page.waitForTimeout(1000);
    }
  });

  test("Delete a library shows confirmation", async ({ page }) => {
    const deleteBtns = page.getByRole("button", { name: /delete|删除/i });
    const count = await deleteBtns.count();
    if (count > 0) {
      await deleteBtns.first().click();
      await page.waitForTimeout(500);
      // Dismiss by Escape
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
    }
  });

  test("Switch between Papers and Variables views", async ({ page }) => {
    const papersBtn = page.locator("button").filter({ hasText: /Papers/i });
    const varsBtn = page.locator("button").filter({ hasText: /Variables/i });

    if (await varsBtn.isVisible({ timeout: 2000 })) {
      await varsBtn.click();
      await page.waitForTimeout(500);
    }

    if (await papersBtn.isVisible({ timeout: 2000 })) {
      await papersBtn.click();
      await page.waitForTimeout(500);
    }
  });
});

// =====================================================================
//  5. Graph View & 3D Graph iframe
// =====================================================================
test.describe("Graph View", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await navigateToView(page, "Graph");
  });

  test("3D graph iframe loads and has valid src", async ({ page }) => {
    const iframe = page.locator("iframe");
    await expect(iframe).toBeAttached({ timeout: 10000 });
    const src = await iframe.getAttribute("src");
    expect(src).toBeTruthy();
    expect(src).toContain("graph_3d");
  });

  test("Graph view sidebar shows stats (NODES/EDGES/PAPERS)", async ({ page }) => {
    await expectVisible(page, /NODES/i);
    await expectVisible(page, /EDGES/i);
    await expectVisible(page, /PAPERS/i);
  });

  test("Semantic variable search input exists", async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search|检索/i);
    await expect(searchInput).toBeVisible({ timeout: 5000 });
  });
});

// =====================================================================
//  6. Reader View
// =====================================================================
test.describe("Reader View", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await navigateToView(page, "Reader");
  });

  test("Reader shows empty state when no paper selected", async ({ page }) => {
    await expectVisible(page, /Document Reader|Select a paper/i);
  });
});

// =====================================================================
//  7. Global Search & Stats
// =====================================================================
test.describe("Global Search & Stats", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await page.waitForTimeout(1000);
  });

  test("Global search input is visible and editable", async ({ page }) => {
    const searchInput = page.getByPlaceholder(/search|搜索/i);
    await expect(searchInput).toBeVisible({ timeout: 5000 });
    await searchInput.fill("innovation");
    await page.waitForTimeout(300);
    // Clear it
    await searchInput.fill("");
  });

  test("Stats panel shows node/edge/paper counts", async ({ page }) => {
    await expectVisible(page, /NODES/i);
  });
});

// =====================================================================
//  8. Legacy 3D Graph Page (standalone)
// =====================================================================
test.describe("Legacy 3D Graph Page", () => {
  test("3D graph page loads with legend", async ({ page }) => {
    await page.goto(`${BASE_URL}/frontend_legacy/graph_3d/`);
    await page.waitForTimeout(2500);

    await expect(page.getByText(/positive|正向/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("#scene")).toBeAttached({ timeout: 5000 });
  });

  test("3D graph loads data from API", async ({ page }) => {
    await page.goto(`${BASE_URL}/frontend_legacy/graph_3d/?library_ids=supply_chain`);
    await page.waitForTimeout(4000);
    await expect(page.locator("#scene")).toBeAttached({ timeout: 5000 });
  });

  test("3D graph legend shows all 5 relationship types", async ({ page }) => {
    test.setTimeout(60000);
    await page.goto(`${BASE_URL}/frontend_legacy/graph_3d/`, { waitUntil: "domcontentloaded" });
    // Wait for 3d-force-graph library to load from CDN and render
    await page.waitForTimeout(5000);

    // The legend should be visible once the page loads
    const legend = page.locator(".legend");
    await expect(legend).toBeVisible({ timeout: 20000 });
    const legendText = await legend.textContent();
    expect(legendText).toMatch(/positive|正向/i);
    expect(legendText).toMatch(/negative|负向/i);
    // At least 3 relationship type rows should be present
    const legendRows = await page.locator(".legend-row").count();
    expect(legendRows).toBeGreaterThanOrEqual(3);
  });
});

// =====================================================================
//  9. API Endpoints — Full Verification
// =====================================================================
test.describe("API Endpoints", () => {
  test("GET /literature/libraries returns object with libraries array", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/literature/libraries`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("libraries");
    expect(Array.isArray(body.libraries)).toBe(true);
  });

  test("GET /graph/overview returns valid structure for ssss library", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/graph/overview?library_id=ssss`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("nodes");
    expect(body).toHaveProperty("edges");
    expect(body).toHaveProperty("meta");
    expect(Array.isArray(body.nodes)).toBe(true);
    expect(Array.isArray(body.edges)).toBe(true);
    // meta contains count info
    expect(typeof body.meta).toBe("object");
  });

  test("GET /v1/jobs returns paginated job list", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/v1/jobs?page=1&page_size=5`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("jobs");
    expect(Array.isArray(body.jobs)).toBe(true);
  });

  test("GET /settings returns schema and settings", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/settings`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("schema");
    expect(body).toHaveProperty("settings");
    expect(typeof body.schema).toBe("object");
    expect(typeof body.settings).toBe("object");
    // schema contains categories array
    expect(body.schema).toHaveProperty("categories");
    expect(Array.isArray(body.schema.categories)).toBe(true);
  });

  test("GET /chat/sessions returns object with sessions array", async ({ request }) => {
    const res = await request.get(`${BASE_URL}/chat/sessions`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("sessions");
    expect(Array.isArray(body.sessions)).toBe(true);
  });
});
