import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL: process.env.KN_GRAPH_TEST_URL || "http://127.0.0.1:8015",
    headless: true,
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
    },
  ],
});
