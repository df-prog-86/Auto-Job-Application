/**
 * Runs the real fill engine in a real browser against a fixture that
 * imitates a Greenhouse application form. Uses Chrome through playwright-core:
 *   CHROME_PATH=/path/to/chrome npm test      (or leave unset to use installed Chrome)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const fixture = pathToFileURL(resolve(here, "fixtures/greenhouse-form.html")).href;

let browser;
let bundle;

const candidate = {
  first_name: "Jane",
  last_name: "Q Doe",
  full_name: "Jane Q Doe",
  email: "jane@example.com",
  phone: "555-0100",
  location: "Boston, MA",
  linkedin_url: "https://linkedin.com/in/janedoe",
};
const baseCtx = {
  candidate,
  answers: { work_authorization: "US citizen", sponsorship_required: false, phone_country: "United States (+1)" },
  learned_answers: {},
};
const resume = { base64: Buffer.from("fake docx bytes").toString("base64"), filename: "Jane Doe_Resume_Acme_2026.docx" };

before(async () => {
  const out = await build({
    entryPoints: [resolve(root, "src/content/fill-page.ts")],
    bundle: true,
    format: "iife",
    write: false,
    tsconfig: resolve(root, "tsconfig.json"),
  });
  bundle = out.outputFiles[0].text;
  browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || undefined,
    channel: process.env.CHROME_PATH ? undefined : "chrome",
  });
});

after(async () => {
  await browser?.close();
});

async function run(ctx = baseCtx, prepare) {
  const page = await browser.newPage();
  await page.goto(fixture);
  if (prepare) await prepare(page);
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [ctx, resume]);
  return { page, report };
}

test("fills the recognized fields and uploads the resume", async () => {
  const { page, report } = await run();
  const v = (sel) => page.$eval(sel, (el) => el.value);
  assert.equal(await v("#first_name"), "Jane");
  assert.equal(await v("#last_name"), "Q Doe");
  assert.equal(await v("#email"), "jane@example.com");
  assert.equal(await v("#phone"), "555-0100");
  assert.equal(await v("#linkedin"), "https://linkedin.com/in/janedoe");
  assert.equal(await page.$eval("#resume", (el) => el.files[0]?.name), "Jane Doe_Resume_Acme_2026.docx");
  assert.equal(await page.$eval("#location", (el) => el.dataset.chosen), "Boston, Massachusetts, United States");
  assert.equal(await page.$eval("#auth", (el) => el.dataset.chosen), "Yes");
  assert.equal(await page.$eval("input[name=sponsor][value=No]", (el) => el.checked), true);
  assert.equal(await page.$eval("input[name=sponsor][value=Yes]", (el) => el.checked), false);
  // Page scripts saw real input events, like a React form would need.
  assert.equal(await page.evaluate(() => window.__inputSeen.first_name), "Jane");
  assert.ok(report.filled.length >= 9, `filled ${report.filled.length}`);
  await page.close();
});

test("the Country box next to Phone gets the saved phone country, and is flagged when none is saved", async () => {
  const a = await run();
  assert.equal(await a.page.$eval("#country", (el) => el.dataset.chosen), "United States +1");
  assert.ok(!a.report.flagged.some((f) => f.label === "Country"));
  await a.page.close();

  const b = await run({ ...baseCtx, answers: { work_authorization: "US citizen", sponsorship_required: false } });
  assert.equal(await b.page.$eval("#country", (el) => el.dataset.chosen ?? ""), "");
  assert.ok(b.report.flagged.some((f) => f.label === "Country"));
  await b.page.close();
});

test("never submits, never ticks consent boxes, never touches voluntary questions", async () => {
  const { page, report } = await run();
  assert.equal(await page.evaluate(() => window.__submitted ?? 0), 0);
  assert.equal(await page.evaluate(() => window.__submitClicked ?? 0), 0);
  assert.equal(await page.$eval("#privacy", (el) => el.checked), false);
  assert.equal(await page.$eval("#gender", (el) => el.value), "");
  assert.equal(await page.$eval("#veteran", (el) => el.value), "");
  assert.equal(report.voluntarySkipped, 2);
  await page.close();
});

test("flags what it cannot answer and leaves optional unknowns alone", async () => {
  const { page, report } = await run();
  const flagged = report.flagged.map((f) => f.label);
  assert.ok(flagged.includes("Why do you want to work here?"), flagged.join("|"));
  assert.ok(flagged.includes("I agree to the privacy policy"), flagged.join("|"));
  assert.equal(await page.$eval("#why", (el) => el.value), "");
  assert.equal(await page.$eval("#how", (el) => el.value), "");
  assert.equal(await page.$eval("#website", (el) => el.value), "");
  assert.ok(!flagged.includes("How did you hear about us?"), "optional unknown must not be flagged");
  assert.ok(report.leftBlank >= 2);
  assert.equal(await page.$eval("#why", (el) => el.getAttribute("data-job-agent")), "flagged");
  assert.equal(await page.$eval("#first_name", (el) => el.getAttribute("data-job-agent")), "filled");
  await page.close();
});

test("uses the candidate's own saved answer for a question they answered before", async () => {
  const ctx = { ...baseCtx, learned_answers: { "why do you want to work here": "I like the mission." } };
  const { page, report } = await run(ctx);
  assert.equal(await page.$eval("#why", (el) => el.value), "I like the mission.");
  assert.ok(!report.flagged.some((f) => f.label.startsWith("Why do you")));
  await page.close();
});

test("never guesses: 'Other' work authorization and a missing sponsorship answer are flagged", async () => {
  const ctx = { ...baseCtx, answers: { work_authorization: "Other" } };
  const { page, report } = await run(ctx);
  assert.equal(await page.$eval("#auth", (el) => el.value), "");
  assert.equal(await page.$eval("input[name=sponsor][value=No]", (el) => el.checked), false);
  const flagged = report.flagged.map((f) => f.label);
  assert.ok(flagged.some((l) => l.startsWith("Are you legally authorized")), flagged.join("|"));
  assert.ok(flagged.some((l) => l.startsWith("Will you now or in the future require")), flagged.join("|"));
  await page.close();
});

test("never overwrites what the candidate already typed, and a second run changes nothing", async () => {
  const { page } = await run(baseCtx, async (p) => {
    await p.fill("#first_name", "Janet");
  });
  assert.equal(await page.$eval("#first_name", (el) => el.value), "Janet");
  const second = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [baseCtx, resume]);
  assert.equal(await page.$eval("#email", (el) => el.value), "jane@example.com");
  assert.ok(second.alreadyFilled >= 6);
  await page.close();
});

test("an ambiguous location is flagged, never silently resolved to the wrong place", async () => {
  const ctx = { ...baseCtx, candidate: { ...candidate, location: "Boston" } };
  const { page, report } = await run(ctx);
  assert.equal(await page.$eval("#location", (el) => el.value), "");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Location")));
  await page.close();
});

test("a location the menu does not offer is left blank and flagged", async () => {
  const ctx = { ...baseCtx, candidate: { ...candidate, location: "Atlantis" } };
  const { page, report } = await run(ctx);
  assert.equal(await page.$eval("#location", (el) => el.value), "");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Location")));
  await page.close();
});

test("the safety rule refuses anything that looks like a final submit", async () => {
  const out = await build({
    entryPoints: [resolve(root, "src/form-engine/safety.ts")],
    bundle: true,
    format: "iife",
    globalName: "safety",
    write: false,
    tsconfig: resolve(root, "tsconfig.json"),
  });
  const page = await browser.newPage();
  await page.setContent(`<form onsubmit="window.sent=(window.sent||0)+1;return false">
    <button id="a" type="submit">Next</button><button id="b">Save</button>
    <button id="c" type="button">Submit Application</button><button id="d" type="button">Continue</button>
    <a id="e" href="#">Apply now</a><input id="f" type="radio" name="r"><div id="g" role="option">Yes</div></form>`);
  await page.addScriptTag({ content: out.outputFiles[0].text });
  const r = await page.evaluate(() => {
    const ids = ["a", "b", "c", "d", "e", "f", "g"];
    const el = (id) => document.getElementById(id);
    return {
      like: Object.fromEntries(ids.map((id) => [id, safety.isSubmitLike(el(id))])),
      clicked: Object.fromEntries(ids.map((id) => [id, safety.safeClick(el(id))])),
      sent: window.sent ?? 0,
      finalText: ["Submit", "Apply", "Send application", "Finish", "Next", "Continue", "Save and continue"].map(safety.isFinalActionText),
    };
  });
  assert.deepEqual(r.like, { a: true, b: true, c: true, d: false, e: true, f: false, g: false });
  assert.deepEqual(r.clicked, { a: false, b: false, c: false, d: false, e: false, f: true, g: true });
  assert.equal(r.sent, 0);
  assert.deepEqual(r.finalText, [true, true, true, true, false, false, false]);
  await page.close();
});
