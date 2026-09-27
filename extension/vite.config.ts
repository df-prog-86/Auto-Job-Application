import { resolve } from "node:path";

import { defineConfig } from "vite";

/**
 * Hand-rolled multi-entry MV3 build: no crx-bundling plugin, so
 * entryFileNames pins each output to the exact path manifest.json expects.
 * Format is plain IIFE for every entry (service worker, popup, content
 * script) — none of them are declared as ES modules in manifest.json, so
 * this avoids Chrome's uneven support for ES-module service workers and
 * content scripts don't support module scripts at all.
 *
 * Rollup refuses to emit more than one chunk for iife/umd output ("code-
 * splitting builds" are ES/CJS-only), and a single `build()` call with
 * multiple `input` entries always produces one chunk per entry — even when,
 * as here, the entries share no runtime code. So each entry is built with
 * its own `vite build` invocation (see package.json's "build" script),
 * selected via ENTRY; a single-entry input is exactly the one-chunk case
 * iife supports, and each bundle inlines its own dependencies independently.
 */
const ENTRIES: Record<string, { input: string; output: string }> = {
  "service-worker": { input: "src/service-worker.ts", output: "service-worker.js" },
  popup: { input: "src/popup/popup.ts", output: "popup.js" },
  "content-detector": { input: "src/content/detector.ts", output: "content/detector.js" },
};

const entryName = process.env.ENTRY;
if (!entryName || !(entryName in ENTRIES)) {
  throw new Error(
    `vite.config.ts requires ENTRY to be set to one of: ${Object.keys(ENTRIES).join(", ")}`,
  );
}
const entry = ENTRIES[entryName];

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: "dist",
    // Only the first build in the sequence should clear dist/; the others
    // would otherwise wipe out each other's output and the copied publicDir.
    emptyOutDir: entryName === "service-worker",
    rollupOptions: {
      input: resolve(__dirname, entry.input),
      output: {
        entryFileNames: entry.output,
        format: "iife",
      },
    },
  },
  publicDir: "public",
});
