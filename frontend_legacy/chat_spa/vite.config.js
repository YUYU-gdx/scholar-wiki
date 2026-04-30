import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5174,
    proxy: {
      "/graph": "http://127.0.0.1:8013",
      "/paper": "http://127.0.0.1:8013",
      "/variable": "http://127.0.0.1:8013",
      "/chat": "http://127.0.0.1:8013",
      "/literature": "http://127.0.0.1:8013"
    }
  }
});
