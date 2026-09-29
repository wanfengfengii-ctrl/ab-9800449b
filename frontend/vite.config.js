import { defineConfig } from "vite";

// 开发态把业务 API 代理到本机后端；生产构建产物由 FastAPI 直接托管
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
