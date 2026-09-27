import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies API calls to the local FastAPI backend so the
// dashboard can be developed with `npm run dev` while the backend runs
// separately on 127.0.0.1:8765 (spec §14). The production build is served
// directly by the backend at /app, where no proxy is needed.
export default defineConfig({
  plugins: [react()],
  // Mirrors the "@/*" -> "src/*" path mapping in tsconfig.app.json.
  resolve: {
    alias: [{ find: /^@\//, replacement: "/src/" }],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  base: "/app/",
});
