import { defineConfig } from "vite";

// 开发模式下把 /api 与 /health 代理到后端；生产由后端托管静态产物
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
