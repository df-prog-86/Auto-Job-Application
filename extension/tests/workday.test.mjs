/** The real fill engine against a fixture shaped like a Workday "My Information" page. */
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const fixture = pathToFileURL(resolve(here, "fixtures/workday-form.html")).href;
let browser;
let bundle;

const ctx = (answers = {}) => ({
  candidate: { first_name: "Jane", last_name: "Doe", full_name: "Jane Doe", email: "jane@example.com", phone: "555-0100", location: "Boston, MA" },
  answers: { phone_country: "United States (+1)", ...answers },
  learned_answers: {},
});
const resume = { base64: Buffer.from("fake docx").toString("base64"), filename: "Jane Doe_Resume.docx" };

before(async () => {
  const out = await build({ entryPoints: [resolve(root, "src/content/fill-page.ts")], bundle: true, format: "iife", write: false, tsconfig: resolve(root, "tsconfig.json") });
  bundle = out.outputFiles[0].text;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, channel: process.env.CHROME_PATH ? undefined : "chrome" });
});
after(async () => { await browser?.close(); });

async function run(c = ctx()) {
  const page = await browser.newPage();
  await page.goto(fixture);
  await page.evaluate(bundle);
  const report = await page.evaluate(([x, r]) => window.__jobAgentFill(x, r), [c, resume]);
  return { page, report };
}

test("fills a Workday page: names, email, phone code, resume, and never presses Next", async () => {
  const { page, report } = await run();
  const v = (sel) => page.$eval(sel, (el) => el.value);
  assert.equal(await v("#fn"), "Jane");
  assert.equal(await v("#ln"), "Doe");
  assert.equal(await v("#em"), "jane@example.com");
  assert.equal(await v("#ph"), "555-0100");
  assert.equal(await v("#ct"), "Boston");
  assert.equal(await page.$eval("#cpc", (b) => b.textContent), "United States of America (+1)");
  assert.equal(await page.$eval("#rf", (el) => el.files[0]?.name), "Jane Doe_Resume.docx");
  assert.equal(await page.evaluate(() => window.__nextClicks), 0, "Save and Continue is never pressed");
  assert.equal(await page.evaluate(() => window.__submitted), 0);
  assert.ok(report.filled.length >= 6, `filled ${report.filled.length}`);
  await page.close();
});

test("State comes from the saved location; dropdowns that cannot be answered for certain are left alone and flagged", async () => {
  const { page, report } = await run();
  assert.equal(await page.$eval("#st", (b) => b.textContent), "Massachusetts");
  assert.equal(await page.$eval("#pdt", (b) => b.textContent), "Select One");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Phone Device Type")), "required Phone Device Type is flagged");
  await page.close();
});

test("a missing phone code answer leaves that dropdown for the person", async () => {
  const c = ctx(); delete c.answers.phone_country;
  const { page } = await run(c);
  assert.equal(await page.$eval("#cpc", (b) => b.textContent), "Select One");
  await page.close();
});
