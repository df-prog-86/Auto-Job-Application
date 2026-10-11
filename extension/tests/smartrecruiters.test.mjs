/** The real fill engine against a replica of SmartRecruiters' shadow-DOM application form. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import { chromium } from "playwright-core";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const html = readFileSync(resolve(here, "fixtures/smartrecruiters-form.html"), "utf8");
const FORM_URL = "https://jobs.smartrecruiters.com/oneclick-ui/company/BostonMedicalCenter/publication/2c4fbfd7-7bb8-4699-9fa2-ccacc65e17fb?dcr_ci=BostonMedicalCenter";
let browser;
let bundle;

const ctx = () => ({
  candidate: {
    first_name: "Jane", preferred_name: "Janie", last_name: "Q Doe", full_name: "Jane Q Doe", email: "jane@example.com",
    phone: "555-0100", location: "Boston, MA", linkedin_url: "https://linkedin.com/in/janedoe",
    recent_title: "Manager", recent_employer: "Huron",
  },
  answers: { work_authorization: "US citizen", sponsorship_required: false, phone_country: "United States (+1)" },
  learned_answers: {},
});
const resume = { base64: Buffer.from("fake docx").toString("base64"), filename: "Jane Doe_Resume_Chartis_2026.docx" };

before(async () => {
  const out = await build({ entryPoints: [resolve(root, "src/content/fill-page.ts")], bundle: true, format: "iife", write: false, tsconfig: resolve(root, "tsconfig.json") });
  bundle = out.outputFiles[0].text;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, channel: process.env.CHROME_PATH ? undefined : "chrome" });
});
after(async () => { await browser?.close(); });

/** Opens the replica at the real SmartRecruiters address (the engine only looks inside shadow roots there). */
async function open(url = FORM_URL) {
  const page = await browser.newPage();
  await page.route("https://jobs.smartrecruiters.com/**", (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto(url);
  return page;
}

/** The value of the real input with this id, wherever it sits in the page's shadow roots. */
const deepValue = (page, id) =>
  page.evaluate((wanted) => {
    const find = (root) => {
      for (const el of root.querySelectorAll("*")) {
        if (el.id === wanted) return el;
        if (el.shadowRoot) { const hit = find(el.shadowRoot); if (hit) return hit; }
      }
      return null;
    };
    const el = find(document);
    return el ? (el.type === "file" ? el.files.length : el.type === "checkbox" ? el.checked : el.value) : "(missing)";
  }, id);

test("fills a SmartRecruiters form inside shadow roots: name, email, phone, LinkedIn and the resume", async () => {
  const page = await open();
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [ctx(), resume]);

  assert.equal(await deepValue(page, "first-name-input"), "Jane");
  assert.equal(await deepValue(page, "last-name-input"), "Q Doe");
  assert.equal(await deepValue(page, "email-input"), "jane@example.com");
  assert.equal(await deepValue(page, "confirm-email-input"), "jane@example.com");
  assert.equal(await deepValue(page, "spl-form-element_5"), "555-0100");
  assert.equal(await deepValue(page, "linkedin-input"), "https://linkedin.com/in/janedoe");
  assert.equal(await deepValue(page, "dz-resume-upload"), 1, "the resume goes in the Resume box");

  // Left alone on purpose.
  assert.equal(await deepValue(page, "dz-apply-with-resume-container"), 0, "the box that parses a resume into the form is not used");
  assert.equal(await deepValue(page, "profile-image"), 0, "no resume in the profile image box");
  assert.equal(await deepValue(page, "spl-form-element_10"), "Boston, MA, US", "City: the one suggestion that is the saved city and state is picked");
  assert.equal(await deepValue(page, "country-search"), "", "the phone's country search box is not a question");
  assert.equal(await deepValue(page, "facebook-input"), "");
  assert.equal(await deepValue(page, "twitter-input"), "");
  assert.equal(await deepValue(page, "website-input"), "");

  // Consent is the person's own click, and nothing is submitted.
  assert.equal(await deepValue(page, "noPolicy"), false);
  assert.ok(report.flagged.some((f) => /privacy notice/i.test(f.label)), "the privacy acknowledgement is flagged for the person");
  assert.equal(await page.evaluate(() => window.__submitClicks), 0);
  await page.close();
});

test("an application link is only filled on the real SmartRecruiters host, and never reaches other sites' shadow roots", async () => {
  // The same page served from another address is read like any ordinary page: its shadow-root boxes are not touched.
  const page = await browser.newPage();
  await page.route("https://example.com/**", (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto("https://example.com/form");
  await page.evaluate(bundle);
  await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [ctx(), resume]);
  assert.equal(await deepValue(page, "first-name-input"), "");
  assert.equal(await deepValue(page, "email-input"), "");
  await page.close();
});

const withHistory = (extra) => ({ ...ctx(), ...extra });
const JOBS = [
  { title: "Financial Analyst", employer: "Huron", location: "Boston, MA", start_date: "2019-03", end_date: "2021-08", current: false, description: "- Built models\n- Led the close" },
  { title: "Senior Associate", employer: "Advent Health", location: "Orlando, FL", start_date: "2021-09", end_date: "2023-06", current: false, description: "Advised health systems" },
  { title: "Manager", employer: "Chartis", location: "Remote", start_date: "2023-07", end_date: null, current: true, description: "Led engagements" },
];
const SCHOOLS = [
  { institution: "Boston College", degree: "Bachelor of Science", field: "Finance", start_date: "2013-09", end_date: "2017" },
  { institution: "Babson College", degree: "Masters in Business Administration", field: "Business Administration", start_date: "2022-01", end_date: "2023-12" },
  { institution: "Rollins", degree: "Bachelor of Arts", field: "Economics", start_date: "2009-08", end_date: "2013-05" },
];

test("adds Experience and Education entries from the saved resume, saving each, and never submits", async () => {
  const page = await open();
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: JOBS, education: SCHOOLS }), resume]);
  const entries = await page.evaluate(() => window.__entries);

  assert.equal(entries.length, 6, "three jobs and three schools were saved, one after another");
  const [job1, job2, job3, school1, school2, school3] = entries;

  assert.equal(job1.Title, "Financial Analyst");
  assert.equal(job1.Company, "Huron", "the top suggestion is picked (the typed text comes first)");
  assert.equal(job1["Office location"], "Boston, MA, US", "a place is the one suggestion that is that city and state");
  assert.equal(job1.from, "2019-03-01");
  assert.equal(job1.to, "2021-08-01");
  assert.match(job1.description, /Built models/);
  assert.equal(job2.Title, "Senior Associate");
  assert.equal(job2.Company, "Advent Health");
  assert.equal(job2["Office location"], "Orlando, FL, US");
  assert.equal(job2.to, "2023-06-01");
  assert.equal(job3.Title, "Manager");
  assert.equal(job3["Office location"], "", "a place the page cannot match is left empty, and the entry is still saved");
  assert.equal(job3.current, true, "a current job is ticked instead of given an end date");
  assert.ok(!job3.to, "no end date was written for the current job");

  // Schools can only be chosen from the page's own list: the exact name, or the one near match.
  assert.equal(school1.Institution, "Boston College", "the top school listed");
  assert.equal(school1.Major, "Finance");
  assert.equal(school1.Degree, "Bachelor of Science");
  assert.equal(school1.from, "2013-09-01");
  assert.ok(!school1.to, "a graduation year with no month is not turned into an invented month");
  assert.equal(school2.Institution, "Babson College");
  assert.equal(school2.to, "2023-12-01");
  assert.equal(school3.Institution, "Rollins College", "\"Rollins\" is matched to the one school that differs only by the word College");

  assert.ok(report.filled.includes("Experience 1: saved") && report.filled.includes("Education 1: saved"));
  assert.equal(await page.evaluate(() => window.__saveClicks), 6, "only each entry's own Save was pressed");
  assert.equal(await page.evaluate(() => window.__submitClicks), 0);
  // The general pass leaves the (now closed) entry forms alone and still does the rest of the page.
  assert.equal(await deepValue(page, "first-name-input"), "Jane");
  await page.close();
});

test("a required date that is not on the resume stops that section: the form is left open and flagged, nothing is guessed", async () => {
  const page = await open();
  await page.evaluate(bundle);
  const jobs = [{ ...JOBS[0], end_date: null }, JOBS[1]];
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: jobs, education: SCHOOLS }), resume]);
  const entries = await page.evaluate(() => window.__entries);

  assert.equal(entries.filter((e) => e.kind === "experience").length, 0, "the incomplete job was not saved, and the next job was not started");
  assert.ok(report.flagged.some((f) => /Experience 1: To/.test(f.label)), "the missing end date is flagged");
  const forms = await page.evaluate(() => document.querySelector("oc-experience").shadowRoot.querySelectorAll("oc-experience-edit-form").length);
  assert.equal(forms, 1, "the form stays open for the person to finish");
  assert.equal(entries.filter((e) => e.kind === "education").length, 3, "the other section still fills");
  assert.equal(await page.evaluate(() => window.__submitClicks), 0);
  await page.close();
});

test("a section that already has an entry is never touched", async () => {
  const page = await open();
  await page.evaluate(() => {
    const card = document.createElement("div");
    card.textContent = "Analyst at Somewhere";
    document.querySelector("oc-experience").shadowRoot.querySelector(".cards").append(card);
  });
  await page.evaluate(bundle);
  await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: JOBS, education: SCHOOLS }), resume]);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.filter((e) => e.kind === "experience").length, 0);
  assert.equal(entries.filter((e) => e.kind === "education").length, 3);
  await page.close();
});

test("an expired SmartRecruiters job is recognized, and a live page or another site is not", async () => {
  const out = await build({
    stdin: { contents: `import { pageIsExpiredSmartRecruiters as f } from "@/form-engine/expired"; window.__expired = f;`, resolveDir: root, loader: "ts" },
    bundle: true, format: "iife", write: false, tsconfig: resolve(root, "tsconfig.json"),
  });
  const code = out.outputFiles[0].text;
  const check = async (host, path, body, title = "Job") => {
    const page = await browser.newPage();
    await page.route(`https://${host}/**`, (route) => route.fulfill({ contentType: "text/html", body: `<!doctype html><title>${title}</title><body>${body}</body>` }));
    await page.goto(`https://${host}${path}`);
    await page.evaluate(code);
    const result = await page.evaluate(() => window.__expired());
    await page.close();
    return result;
  };
  const posting = "/WynnResorts/744000132299989-financial-analyst";
  assert.equal(await check("jobs.smartrecruiters.com", posting, "<h1>Financial Analyst</h1><p>Compensation</p><p>This job has expired</p><p>Sorry, this job has expired</p>"), true, "an expired posting page");
  assert.equal(await check("jobs.smartrecruiters.com", "/oneclick-ui/company/X/publication/1/expired", "<p>Nothing here</p>", "This job ad has expired"), true, "the form address that redirects to /expired");
  assert.equal(await check("jobs.smartrecruiters.com", posting, "<h1>Financial Analyst</h1><a>I'm interested</a>"), false, "a live posting");
  assert.equal(await check("example.com", posting, "<p>This job has expired</p>"), false, "another site is never judged");
});

test("works the way Chrome runs an extension (an isolated world that cannot read the page's own properties)", async () => {
  const page = await open();
  const cdp = await page.context().newCDPSession(page);
  const { frameTree } = await cdp.send("Page.getFrameTree");
  const { executionContextId: contextId } = await cdp.send("Page.createIsolatedWorld", { frameId: frameTree.frame.id, worldName: "ext" });
  const run = async (expression) => {
    const r = await cdp.send("Runtime.evaluate", { expression, contextId, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  await run(bundle);
  const report = await run(`window.__jobAgentFill(${JSON.stringify(withHistory({ experience: JOBS.slice(0, 1), education: SCHOOLS.slice(2) }))}, null)`);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.length, 2, JSON.stringify(report.flagged));
  assert.equal(entries[0].Title, "Financial Analyst");
  assert.equal(entries[0].from, "2019-03-01", "month and year are accepted without reading the picker's own value");
  assert.equal(entries[1].Institution, "Rollins College");
  await page.close();
});

test("a suggestion list with plain row text, chosen only by a real mouse press, still gets its row picked", async () => {
  const page = await open(FORM_URL + "&plain=1");
  await page.evaluate(bundle);
  await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: [], education: SCHOOLS.slice(1, 2) }), resume]);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].Institution, "Babson College");
  await page.close();
});

test("the page-world helper does the picking while the extension script only passes the work along", async () => {
  const helper = (await build({ entryPoints: [resolve(root, "src/content/sr-main.ts")], bundle: true, format: "iife", write: false, tsconfig: resolve(root, "tsconfig.json") })).outputFiles[0].text;
  const page = await open();
  await page.evaluate(helper); // the page's own world
  const cdp = await page.context().newCDPSession(page);
  const { frameTree } = await cdp.send("Page.getFrameTree");
  const { executionContextId: contextId } = await cdp.send("Page.createIsolatedWorld", { frameId: frameTree.frame.id, worldName: "ext" });
  const run = async (expression) => {
    const r = await cdp.send("Runtime.evaluate", { expression, contextId, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  await run(bundle);
  const report = await run(`window.__jobAgentFill(${JSON.stringify(withHistory({ experience: JOBS.slice(0, 1), education: SCHOOLS.slice(2) }))}, null)`);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.length, 2, JSON.stringify(report.flagged));
  assert.equal(entries[0].Company, "Huron");
  assert.equal(entries[1].Institution, "Rollins College");
  assert.ok(report.filled.includes("Experience 1: saved"), "the helper's result is passed back into the report");
  await page.close();
});

test("when the page ignores clicks and only takes a pick made with the keyboard, the row is still chosen and accepted", async () => {
  const page = await open(FORM_URL + "&keys=1");
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: [], education: SCHOOLS.slice(1, 2) }), resume]);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.length, 1, JSON.stringify(report.flagged));
  assert.equal(entries[0].Institution, "Babson College");
  await page.close();
});

test("a suggestion list that is redrawn after it first appears still gets its top row picked", async () => {
  const page = await open(FORM_URL + "&slow=1");
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: JOBS.slice(0, 1), education: SCHOOLS.slice(1, 2) }), resume]);
  const entries = await page.evaluate(() => window.__entries);
  assert.equal(entries.length, 2, JSON.stringify(report.flagged));
  assert.equal(entries[0].Title, "Financial Analyst");
  assert.equal(entries[1].Institution, "Babson College");
  await page.close();
});
