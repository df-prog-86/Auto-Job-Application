import { resolve } from "node:path";

import { defineConfig } from "vite";

/**
 * Hand-rolled multi-entry MV3 build: no crx-bundling plugin, so
 * entryFileNames pins each output to the exact path manifest.json expects.
 * Format is plain IIFE for every entry (service worker, popup, content
 * script) — none of them are declared as ES modules in manifest.json, so
 * this avoids Chrome's uneven support for ES-module service workers and
 * content scripts don't support module scripts at all. Shared local
 * modules imported by more than one entry are duplicated into each
 * bundle by Rollup; that's fine at this size and keeps the manifest simple.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        "service-worker": resolve(__dirname, "src/service-worker.ts"),
        popup: resolve(__dirname, "src/popup/popup.ts"),
        "content/detector": resolve(__dirname, "src/content/detector.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        format: "iife",
      },
    },
  },
  publicDir: "public",
});
