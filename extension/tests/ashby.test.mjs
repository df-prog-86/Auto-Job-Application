/** The real fill engine against a fixture shaped like an Ashby application form. */
import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const fixture = pathToFileURL(resolve(here, "fixtures/ashby-form.html")).href;
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

test("fills an Ashby form: text fields, recent role, location, Yes/No buttons, resume", async () => {
  const { page, report } = await run();
  const v = (sel) => page.$eval(sel, (el) => el.value);
  assert.equal(await v("#_systemfield_name"), "Jane Q Doe");
  assert.equal(await v("#pref"), "Janie");
  assert.equal(await v("#_systemfield_email"), "jane@example.com");
  assert.equal(await v("#phone"), "555-0100");
  assert.equal(await v("#title"), "Manager");
  assert.equal(await v("#employer"), "Huron");
  assert.equal(await v("#li"), "https://linkedin.com/in/janedoe");
  assert.equal(await page.$eval("input[role=combobox]", (el) => el.dataset.chosen), "Boston, Massachusetts, United States");
  const pressed = (id, opt) => page.$eval(`#${id} button[data-option=${opt}]`, (b) => b.getAttribute("aria-pressed"));
  assert.equal(await pressed("q-auth", "yes"), "true");
  assert.equal(await pressed("q-sponsor", "no"), "true");
  assert.equal(await page.$eval("#_systemfield_resume", (el) => el.files[0]?.name), "Jane Doe_Resume_Chartis_2026.docx");
  assert.equal(await page.$eval("input[type=file]", (el) => el.files.length), 0, "the autofill upload is left alone");
  assert.ok(report.filled.length >= 9, `filled ${report.filled.length}`);
  await page.close();
});

test("pressing Yes/No never submits the form, and nothing else is touched", async () => {
  const { page, report } = await run();
  assert.equal(await page.evaluate(() => window.__submitted), 0);
  assert.equal(await page.$$eval("input[name=pron]:checked, input[name=gender]:checked, input[name=race]:checked, input[name=vet]:checked", (n) => n.length), 0);
  assert.equal(await page.$eval("#q-employed button[data-option=yes]", (b) => b.getAttribute("aria-pressed")), "false");
  assert.equal(await page.$eval("#q-employed button[data-option=no]", (b) => b.getAttribute("aria-pressed")), "false");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Have you ever been employed")), "unknown required question is flagged");
  assert.ok(report.voluntarySkipped >= 4, "pronouns, gender, race and veteran are voluntary");
  // Agreeing to terms is never done for the person, even when it is a Yes/No button, and it is flagged instead.
  const terms = await page.$$eval("#q-terms button", (bs) => bs.map((b) => b.getAttribute("aria-pressed")));
  assert.deepEqual(terms, ["false", "false"]);
  assert.ok(report.flagged.some((f) => f.label.startsWith("Terms of Use")));
  await page.close();
});

test("a missing sponsorship answer leaves that question for the person", async () => {
  const c = ctx(); delete c.answers.sponsorship_required;
  const { page, report } = await run(c);
  assert.equal(await page.$eval("#q-sponsor button[data-option=no]", (b) => b.getAttribute("aria-pressed")), "false");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Will you now or in the future")));
  await page.close();
});

const checkedLabel = (page, name) => page.$eval(`input[name=${name}]:checked`, (el) => document.querySelector(`label[for="${el.id}"]`).textContent.trim()).catch(() => null);

test("saved gender, race and veteran choices are filled; pronouns stay untouched", async () => {
  const { page } = await run(ctx({ eeo_gender: "male", eeo_race: "asian", eeo_veteran: "not_protected" }));
  assert.equal(await checkedLabel(page, "gender"), "Male");
  assert.equal(await checkedLabel(page, "race"), "Asian (Not Hispanic or Latino)");
  assert.equal(await checkedLabel(page, "vet"), "I am not a protected veteran");
  assert.equal(await page.$$eval("input[name=pron]:checked", (n) => n.length), 0);
  assert.equal(await page.evaluate(() => window.__submitted), 0);
  await page.close();
});

test("decline choices are filled, and skip leaves the fields alone", async () => {
  let r = await run(ctx({ eeo_gender: "decline", eeo_race: "decline", eeo_veteran: "decline" }));
  assert.equal(await checkedLabel(r.page, "gender"), "Decline to self-identify");
  assert.equal(await checkedLabel(r.page, "race"), "Decline to self-identify");
  assert.equal(await checkedLabel(r.page, "vet"), "I decline to self-identify for protected veteran status");
  await r.page.close();
  r = await run(ctx({ eeo_gender: "skip", eeo_race: "skip", eeo_veteran: "skip" }));
  assert.equal(await r.page.$$eval("input[name=gender]:checked, input[name=race]:checked, input[name=vet]:checked", (n) => n.length), 0);
  await r.page.close();
});
