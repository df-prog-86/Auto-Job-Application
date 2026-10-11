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
  assert.equal(await deepValue(page, "spl-form-element_10"), "", "the City typeahead needs a suggestion picked, so it is left to the person");
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
