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
  { title: "Senior Associate", employer: "Chartis", location: null, start_date: "2021-09", end_date: null, current: true, description: "Advised health systems" },
];
const SCHOOLS = [
  { institution: "Boston College", degree: "Bachelor of Science", field: "Finance", start_date: "2013-09", end_date: "2017" },
  { institution: "Babson College", degree: "Masters in Business Administration", field: "Business Administration", start_date: "2022-01", end_date: "2023-12" },
];

test("adds Experience and Education entries from the saved resume, saving each, and never submits", async () => {
  const page = await open();
  await page.evaluate(bundle);
  const report = await page.evaluate(([c, r]) => window.__jobAgentFill(c, r), [withHistory({ experience: JOBS, education: SCHOOLS }), resume]);
  const entries = await page.evaluate(() => window.__entries);

  assert.equal(entries.length, 4, "two jobs and two schools were saved, one after another");
  const [job1, job2, school, school2] = entries;
  assert.equal(school2.Institution, "Babson College");
  assert.equal(school2.to, "2023-12-01");
  assert.equal(job1.Title, "Financial Analyst");
  assert.equal(job1.Company, "Huron", "the exact text is picked, never a similar-looking suggestion (Huron Consulting Group)");
  assert.equal(job1["Office location"], "Boston, MA");
  assert.equal(job1.from, "2019-03-01");
  assert.equal(job1.to, "2021-08-01");
  assert.match(job1.description, /Built models/);
  assert.equal(job2.Title, "Senior Associate");
  assert.equal(job2.current, true, "a current job is ticked instead of given an end date");
  assert.ok(!job2.to, "no end date was written for the current job");
  assert.equal(school.Institution, "Boston College");
  assert.equal(school.Major, "Finance");
  assert.equal(school.Degree, "Bachelor of Science");
  assert.equal(school.from, "2013-09-01");
  assert.ok(!school.to, "a graduation year with no month is not turned into an invented month");

  assert.ok(report.filled.includes("Experience 1: saved") && report.filled.includes("Education 1: saved"));
  assert.equal(await page.evaluate(() => window.__saveClicks), 4, "only each entry's own Save was pressed");
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
  assert.equal(entries.filter((e) => e.kind === "education").length, 2, "the other section still fills");
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
  assert.equal(entries.filter((e) => e.kind === "education").length, 2);
  await page.close();
});
