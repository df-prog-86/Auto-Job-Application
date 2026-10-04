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
  answers: { phone_country: "United States (+1)", work_authorization: "US citizen", ...answers },
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

test("questionnaire dropdowns are read from their legend: work authorization answered, background check consent never", async () => {
  const { page, report } = await run();
  assert.equal(await page.$eval("#q1", (b) => b.textContent), "Yes");
  assert.equal(await page.$eval("#q2", (b) => b.textContent), "Select One", "consenting to an investigation is the person's own choice");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Will you authorize such an investigation")));
  await page.close();
});

test("voluntary disclosures: left alone unless chosen, then matched to Workday's exact wording", async () => {
  let r = await run();
  for (const id of ["gen", "rac", "vet"]) assert.equal(await r.page.$eval(`#${id}`, (b) => b.textContent), "Select One");
  await r.page.close();
  r = await run(ctx({ eeo_gender: "male", eeo_race: "hispanic", eeo_veteran: "not_protected" }));
  assert.equal(await r.page.$eval("#gen", (b) => b.textContent), "Male");
  assert.equal(await r.page.$eval("#rac", (b) => b.textContent), "Hispanic or Latino (United States of America)");
  assert.equal(await r.page.$eval("#vet", (b) => b.textContent), "o I am not a protected veteran in any of the categories above.");
  await r.page.close();
  r = await run(ctx({ eeo_gender: "decline", eeo_race: "decline", eeo_veteran: "decline" }));
  assert.equal(await r.page.$eval("#gen", (b) => b.textContent), "Prefer Not to Identify");
  assert.equal(await r.page.$eval("#rac", (b) => b.textContent), "Prefer Not to Identify (United States of America)");
  assert.equal(await r.page.$eval("#vet", (b) => b.textContent), "o I choose not to self-identity as a protected veteran.");
  await r.page.close();
  r = await run(ctx({ eeo_race: "asian", eeo_veteran: "protected" }));
  assert.equal(await r.page.$eval("#rac", (b) => b.textContent), "Asian (Not Hispanic or Latino) (United States of America)");
  assert.equal(await r.page.$eval("#vet", (b) => b.textContent), "o I identify as one or more of the classifications of protected veterans listed above.");
  await r.page.close();
});

test("the federal disability form: name, date and boxes are left for the person", async () => {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(resolve(here, "fixtures/workday-disability.html")).href);
  await page.evaluate(bundle);
  const report = await page.evaluate(([x, r]) => window.__jobAgentFill(x, r), [ctx(), resume]);
  assert.equal(await page.$eval("#nm", (el) => el.value), "");
  assert.equal(await page.$eval("#dt", (el) => el.value), "");
  assert.equal(await page.$$eval("input[type=checkbox]:checked", (n) => n.length), 0);
  assert.ok(report.flagged.some((f) => f.label === "Name"));
  assert.ok(report.flagged.some((f) => f.label === "Date"));
  await page.close();
});

const flowUrl = "https://test.myworkdayjobs.com/flow";
async function runFlow(page, c = ctx()) {
  const html = (await import("node:fs")).readFileSync(resolve(here, "fixtures/workday-flow.html"), "utf8");
  await page.route("https://test.myworkdayjobs.com/**", (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto(`${flowUrl}${page.__start ?? ""}`);
  await page.evaluate(bundle);
  return page.evaluate(([x, r]) => window.__jobAgentFill(x, r), [c, resume]);
}

test("Workday: moves past a finished page, then stops at the page that needs a tick", async () => {
  const page = await browser.newPage();
  const report = await runFlow(page);
  assert.equal(await page.$eval("h2", (h) => h.textContent), "Voluntary Disclosures");
  assert.equal(report.pagesAdvanced, 1);
  assert.match(report.stoppedBecause, /consent|tick|needs you/i);
  assert.deepEqual(await page.evaluate(() => window.__clicks), ["Save and Continue"]);
  assert.equal(await page.$eval("#agree", (el) => el.checked), false, "consent is never ticked");
  await page.close();
});

test("Workday: a page with a missing required answer is not advanced", async () => {
  const c = ctx(); c.candidate.last_name = "";
  const page = await browser.newPage();
  const report = await runFlow(page, c);
  assert.equal(report.pagesAdvanced, 0);
  assert.deepEqual(await page.evaluate(() => window.__clicks), []);
  assert.equal(await page.$eval("h2", (h) => h.textContent), "My Information");
  await page.close();
});

test("Workday: the Review page and its Submit button are never pressed", async () => {
  const page = await browser.newPage();
  page.__start = "?page=review";
  const report = await runFlow(page);
  assert.equal(report.pagesAdvanced, 0);
  assert.deepEqual(await page.evaluate(() => window.__clicks), []);
  assert.equal(await page.evaluate(() => window.__submits), 0);
  assert.match(report.stoppedBecause, /last step|Review/i);
  await page.close();
});

test("Workday walker: Apply, Apply Manually, waits at sign-in without touching the password, then fills and stops at Review", async () => {
  const html = (await import("node:fs")).readFileSync(resolve(here, "fixtures/workday-entry.html"), "utf8");
  const page = await browser.newPage();
  await page.route("https://test.myworkdayjobs.com/**", (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto("https://test.myworkdayjobs.com/job/1");
  await page.evaluate(bundle);
  assert.equal(await page.evaluate(([x, r]) => window.__jobAgentWorkday(x, r), [ctx(), resume]), "started");
  assert.equal(await page.evaluate(([x, r]) => window.__jobAgentWorkday(x, r), [ctx(), resume]), "already running");

  await page.waitForSelector("#pw", { timeout: 15000 });
  await page.waitForFunction(() => document.getElementById("em").value !== "", null, { timeout: 5000 });
  assert.equal(await page.$eval("#em", (el) => el.value), "jane@example.com", "only the email is typed");
  await page.waitForTimeout(1500);
  assert.equal(await page.$eval("#pw", (el) => el.value), "", "the password is never touched");
  assert.equal(await page.evaluate(() => window.__jobAgentOutcome?.type), "WORKDAY_WAITING");
  assert.equal(await page.evaluate(() => window.__pressed.includes("next")), false, "waits for the person");

  await page.click("#signin"); // the person signs in
  await page.waitForFunction(() => window.__jobAgentOutcome?.type === "WORKDAY_DONE", null, { timeout: 20000 });
  const pressed = await page.evaluate(() => window.__pressed);
  assert.deepEqual(pressed, ["adventureButton", "applyManually", "signin", "next"]);
  assert.equal(await page.evaluate(() => window.__submits), 0);
  assert.equal(await page.$eval("h2", (h) => h.textContent), "Review");
  const out = await page.evaluate(() => window.__jobAgentOutcome);
  assert.equal(out.report.pagesAdvanced, 1);
  await page.close();
});

test("address, postal code and phone type come from the saved answers; Address Line 2 is left alone", async () => {
  const { page, report } = await run(ctx({ address_line1: "1 Main St", postal_code: "02118", phone_device_type: "Mobile" }));
  assert.equal(await page.$eval("#a1", (el) => el.value), "1 Main St");
  assert.equal(await page.$eval("#pc", (el) => el.value), "02118");
  assert.equal(await page.$eval("#pdt", (b) => b.textContent), "Mobile");
  assert.equal(await page.$eval("#a2", (el) => el.value), "");
  assert.ok(!report.flagged.some((f) => /Address Line 1|Postal|Phone Device/.test(f.label)));
  await page.close();
});

test("without saved address answers, those required fields are flagged, never guessed", async () => {
  const { page, report } = await run();
  assert.equal(await page.$eval("#a1", (el) => el.value), "");
  assert.equal(await page.$eval("#pc", (el) => el.value), "");
  for (const label of ["Address Line 1", "Postal Code", "Phone Device Type"]) {
    assert.ok(report.flagged.some((f) => f.label.startsWith(label)), `${label} flagged`);
  }
  await page.close();
});

// ---- My Experience: repeating Work Experience / Education rows ----
const history = () => ({
  experience: [
    { title: "Senior Analyst", employer: "Acme Health", location: "Boston, MA", start_date: "2021-03", end_date: null, current: true, description: "Built denial dashboards\nCut AR days by 12%" },
    { title: "Analyst", employer: "Beta Billing", location: "Remote", start_date: "2018-06", end_date: "2021-02", current: false, description: "Reconciled payer remits" },
  ],
  education: [{ institution: "State University", degree: "Bachelor of Science", field: "Finance", start_date: "2014-09", end_date: "2018-05" }],
});
async function runExperience(h = history(), setup) {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(resolve(here, "fixtures/workday-experience.html")).href);
  if (setup) await page.evaluate(setup);
  await page.evaluate(bundle);
  const c = { ...ctx(), ...h };
  c.candidate.linkedin_url = "https://www.linkedin.com/in/jane";
  const report = await page.evaluate(([x, r]) => window.__jobAgentFill(x, r), [c, resume]);
  return { page, report };
}
const rowVals = (page, sel) => page.$$eval(`${sel} .row`, (rows) => rows.map((r) => ({
  head: r.querySelector("h4").textContent,
  texts: Array.from(r.querySelectorAll("input[type=text], textarea")).map((i) => i.value),
  cur: r.querySelector(".cur")?.checked,
  dates: Array.from(r.querySelectorAll("[data-automation-id^=dateSection]")).map((i) => i.value),
  deg: r.querySelector(".deg")?.textContent,
  toHidden: r.querySelector(".to")?.hidden,
})));

test("experience: adds a row per role, fills title/company/location/dates/bullets, current job has no end date", async () => {
  const { page, report } = await runExperience();
  const work = await rowVals(page, "#workrows");
  assert.equal(work.length, 2);
  assert.deepEqual(work[0].texts, ["Senior Analyst", "Acme Health", "Boston, MA", "Built denial dashboards\nCut AR days by 12%"]);
  assert.equal(work[0].cur, true);
  assert.deepEqual(work[0].dates, ["03", "2021", "", ""]);
  assert.deepEqual(work[1].texts, ["Analyst", "Beta Billing", "Remote", "Reconciled payer remits"]);
  assert.deepEqual(work[1].dates, ["06", "2018", "02", "2021"]);
  assert.equal(work[1].cur, false);
  assert.equal(await page.evaluate(() => window.__nextClicks), 0);
  assert.equal(await page.evaluate(() => window.__submitted), 0);
  assert.equal(await page.evaluate(() => window.__adds), 1, "only Add Another was pressed, once");
  assert.ok(!report.flagged.some((f) => /Work Experience/.test(f.label)), JSON.stringify(report.flagged));
  await page.close();
});

test("education: school, degree matched to the dropdown's wording, field, and years", async () => {
  const { page } = await runExperience();
  const edu = await rowVals(page, "#edurows");
  assert.equal(edu.length, 1);
  assert.deepEqual(edu[0].texts, ["State University", "Finance", ""]);
  assert.equal(edu[0].deg, "Bachelor's Degree");
  assert.deepEqual(edu[0].dates, ["2014", "2018"]);
  await page.close();
});

test("websites: the one required URL gets the LinkedIn address", async () => {
  const { page } = await runExperience();
  assert.equal(await page.$eval("#url", (i) => i.value), "https://www.linkedin.com/in/jane");
  await page.close();
});

test("experience: rows that already hold something are never touched or added to", async () => {
  const { page } = await runExperience(history(), () => {
    document.querySelector("#workrows .jt").value = "My own title";
  });
  const work = await rowVals(page, "#workrows");
  assert.equal(work.length, 1);
  assert.deepEqual(work[0].texts, ["My own title", "", "", ""]);
  assert.equal(await page.evaluate(() => window.__adds), 0, "no row was added");
  await page.close();
});

test("experience: a role with no start date is flagged, not guessed", async () => {
  const h = history(); h.experience = [{ ...h.experience[1], start_date: null }];
  const { page, report } = await runExperience(h);
  assert.ok(report.flagged.some((f) => /Work Experience 1: From/.test(f.label)));
  const work = await rowVals(page, "#workrows");
  assert.deepEqual(work[0].dates.slice(0, 2), ["", ""]);
  await page.close();
});

test("experience: an unknown degree is left for the person and flagged", async () => {
  const h = history(); h.education[0].degree = "Diploma of Basket Weaving";
  const { page, report } = await runExperience(h);
  const edu = await rowVals(page, "#edurows");
  assert.equal(edu[0].deg, "Select One");
  assert.ok(report.flagged.some((f) => f.label.startsWith("Degree")));
  await page.close();
});

test("experience: with no saved history the rows are left blank and the required ones flagged", async () => {
  const { page, report } = await runExperience({ experience: [], education: [] });
  const work = await rowVals(page, "#workrows");
  assert.deepEqual(work[0].texts, ["", "", "", ""]);
  assert.ok(report.flagged.some((f) => f.label.startsWith("Job Title")));
  assert.equal(await page.evaluate(() => window.__adds), 0);
  await page.close();
});

// ---- Tegria style: sections start empty with an "Add" button, ids carry the row, degrees are codes ----
async function runTegria(h = history()) {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(resolve(here, "fixtures/workday-experience-tegria.html")).href);
  await page.evaluate(bundle);
  const report = await page.evaluate(([x, r]) => window.__jobAgentFill(x, r), [{ ...ctx(), ...h }, resume]);
  return { page, report };
}
const tegriaRows = (page, box) => page.$$eval(`#${box} .row`, (rows) => rows.map((r) => ({
  texts: Array.from(r.querySelectorAll("input[type=text], textarea")).map((i) => i.value),
  cur: r.querySelector(".cur")?.checked,
  dates: Array.from(r.querySelectorAll("[data-automation-id^=dateSection]")).map((i) => i.value),
  deg: r.querySelector(".deg")?.textContent,
})));

test("Tegria style: empty sections get a row per role/school via Add, then Add Another", async () => {
  const { page, report } = await runTegria();
  const work = await tegriaRows(page, "workbox");
  assert.equal(work.length, 2);
  assert.deepEqual(work[0].texts, ["Senior Analyst", "Acme Health", "Boston, MA", "Built denial dashboards\nCut AR days by 12%"]);
  assert.equal(work[0].cur, true);
  assert.deepEqual(work[0].dates, ["03", "2021", "", ""]);
  assert.deepEqual(work[1].dates, ["06", "2018", "02", "2021"]);
  const edu = await tegriaRows(page, "edubox");
  assert.equal(edu.length, 1);
  assert.equal(edu[0].deg, "BS", "Bachelor of Science -> the BS code");
  assert.deepEqual(edu[0].texts, ["State University", "Finance", ""]);
  assert.deepEqual(edu[0].dates, ["2014", "2018"]);
  assert.equal(await page.evaluate(() => window.__certAdds), 0, "Certifications is never touched");
  assert.equal(await page.evaluate(() => window.__nextClicks), 0);
  assert.ok(!report.flagged.some((f) => /Work Experience|Education/.test(f.label)), JSON.stringify(report.flagged));
  await page.close();
});

test("Tegria style: with no saved history nothing is added", async () => {
  const { page } = await runTegria({ experience: [], education: [] });
  assert.equal((await tegriaRows(page, "workbox")).length, 0);
  assert.equal(await page.evaluate(() => window.__adds), 0);
  await page.close();
});

test("Tegria style: Business Administration or an unknown degree is not forced onto a code", async () => {
  const h = history(); h.education[0].degree = "Bachelor of Business Administration";
  const { page } = await runTegria(h);
  assert.equal((await tegriaRows(page, "edubox"))[0].deg, "Select One");
  await page.close();
});
