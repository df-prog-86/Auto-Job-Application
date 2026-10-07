/** Recognizing the employer's "application received" page. */
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(mkdtempSync(join(tmpdir(), "sub-")), "submitted.mjs");
await build({ entryPoints: [resolve(root, "src/form-engine/submitted.ts")], bundle: true, format: "esm", outfile: out });
const { looksSubmitted } = await import(pathToFileURL(out).href);

test("confirmation wording is recognized", () => {
  assert.ok(looksSubmitted("https://job-boards.greenhouse.io/acme/jobs/1", "Thank you for applying to Acme."));
  assert.ok(looksSubmitted("https://jobs.ashbyhq.com/acme/1/application", "Your application was successfully submitted."));
  assert.ok(looksSubmitted("https://acme.wd5.myworkdayjobs.com/en-US/x/job/y", "Application Submitted\nThank you"));
});

test("a confirmation address counts when the page is not still a form", () => {
  assert.ok(looksSubmitted("https://job-boards.greenhouse.io/acme/jobs/1/confirmation", "All done"));
  assert.ok(!looksSubmitted("https://job-boards.greenhouse.io/acme/jobs/1/confirmation", "Review your answers. Submit application"));
});

test("a form or a posting page is not a submission", () => {
  assert.ok(!looksSubmitted("https://job-boards.greenhouse.io/acme/jobs/1", "Apply for this job. First name. Resume. Submit application"));
  assert.ok(!looksSubmitted("https://jobs.ashbyhq.com/acme/1", "We will review applications as they are submitted."));
  assert.ok(!looksSubmitted("not a url", "Thank you"));
});
