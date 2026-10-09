/** The real fill engine against a fixture shaped like an Lever application form. */
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const fixture = pathToFileURL(resolve(here, "fixtures/lever-form.html")).href;
let browser;
let bundle;

const ctx = (answers = {}) => ({
  candidate: {
    first_name: "Jane", preferred_name: "Janie", last_name: "Q Doe", full_name: "Jane Q Doe", email: "jane@example.com",
    phone: "555-0100", location: "Boston, MA", linkedin_url: "https://linkedin.com/in/janedoe",
    recent_title: "Manager", recent_employer: "Huron",
  },
  answers: { work_authorization: "US citizen", sponsorship_required: false, phone_country: "United States (+1)", ...answers },
  learned_answers: {},
});
const resume = { base64: Buffer.from("fake docx").toString("base64"), filename: "Jane Doe_Resume_Chartis_2026.docx" };

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

test("fills a Lever form: name, email, phone, company, LinkedIn, Yes/No questions and the resume", async () => {
  const { page, report } = await run();
  const v = (sel) => page.$eval(sel, (el) => el.value);
  assert.equal(await v("input[name=name]"), "Jane Q Doe");
  assert.equal(await v("input[name=email]"), "jane@example.com");
  assert.equal(await v("input[name=phone]"), "555-0100");
  assert.equal(await v("input[name=org]"), "Huron");
  assert.equal(await v("input[name='urls[LinkedIn]']"), "https://linkedin.com/in/janedoe");
  const checked = (name) => page.$eval(`input[name='${name}']:checked`, (el) => el.value).catch(() => null);
  assert.equal(await checked("cards[1][field0]"), "Yes");
  assert.equal(await checked("cards[2][field0]"), "No");
  assert.equal(await page.$eval("#resume-upload-input", (el) => el.files[0]?.name), "Jane Doe_Resume_Chartis_2026.docx");
  assert.ok(report.filled.length >= 8, `filled ${report.filled.length}`);
  await page.close();
});

test("never submits, leaves an unknown required question and the voluntary survey alone", async () => {
  const { page, report } = await run();
  assert.equal(await page.evaluate(() => window.__submitted), 0);
  assert.equal(await page.$$eval("input[name='cards[3][field0]']:checked", (n) => n.length), 0);
  assert.ok(report.flagged.some((f) => f.label.startsWith("Have you ever worked for Acme")), "flagged for the person");
  assert.equal(await page.$eval("select[name='eeo[gender]']", (el) => el.value), "");
  await page.close();
});

test("a missing sponsorship answer leaves that question for the person", async () => {
  const c = ctx(); delete c.answers.sponsorship_required;
  const { page } = await run(c);
  assert.equal(await page.$$eval("input[name='cards[2][field0]']:checked", (n) => n.length), 0);
  await page.close();
});
