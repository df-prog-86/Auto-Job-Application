/** "Remember my answer": a question the person answers by hand is offered for saving, and only that. */
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
let browser;
let bundle;

const ctx = () => ({
  candidate: { first_name: "A", last_name: "B", full_name: "A B", email: "a@b.com" },
  answers: {},
  learned_answers: {},
});
const html = `<form>
  <label for="a">Do you have a relative who works here? *</label>
  <select id="a" required><option value="">Select</option><option>Yes</option><option>No</option></select>
  <label for="b">I agree to the terms *</label>
  <select id="b" required><option value="">Select</option><option>Yes</option></select>
</form>`;

before(async () => {
  const out = await build({ entryPoints: [resolve(root, "src/content/fill-page.ts")], bundle: true, format: "iife", write: false, tsconfig: resolve(root, "tsconfig.json") });
  bundle = out.outputFiles[0].text;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, channel: process.env.CHROME_PATH ? undefined : "chrome" });
});
after(async () => { await browser?.close(); });

async function start() {
  const page = await browser.newPage();
  await page.setContent(html);
  await page.evaluate(() => {
    window.__sent = [];
    window.chrome = { runtime: { id: "x", sendMessage: (m) => window.__sent.push(m) } };
  });
  await page.evaluate(bundle);
  await page.evaluate((c) => window.__jobAgentFill(c, null), ctx());
  return page;
}

test("an answer given by hand is offered, saved only on request, and an agreement is never offered", async () => {
  const page = await start();
  await page.selectOption("#a", "No");
  await page.selectOption("#b", "Yes");
  await page.waitForSelector("#job-agent-learn-note", { timeout: 8000 });
  const text = await page.textContent("#job-agent-learn-note");
  assert.match(text, /relative who works here/);
  assert.doesNotMatch(text, /agree/i);
  assert.deepEqual(await page.evaluate(() => window.__sent), []); // nothing is sent until they press Save
  await page.click('#job-agent-learn-note button:has-text("Save for next time")');
  assert.deepEqual(await page.evaluate(() => window.__sent), [
    { type: "LEARN_ANSWERS", answers: [{ label: "Do you have a relative who works here?", value: "No" }] },
  ]);
  assert.equal(await page.$("#job-agent-learn-note"), null);
  await page.close();
});

test("Not now sends nothing and does not ask again", async () => {
  const page = await start();
  await page.selectOption("#a", "Yes");
  await page.waitForSelector("#job-agent-learn-note", { timeout: 8000 });
  await page.click('#job-agent-learn-note button:has-text("Not now")');
  await page.waitForTimeout(4500);
  assert.equal(await page.$("#job-agent-learn-note"), null);
  assert.deepEqual(await page.evaluate(() => window.__sent), []);
  await page.close();
});
