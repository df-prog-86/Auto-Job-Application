/** Pure rules for recognizing fields and choosing values (no browser needed). */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(mkdtempSync(join(tmpdir(), "canon-")), "canonical.mjs");
await build({
  entryPoints: [resolve(root, "src/form-engine/canonical.ts")],
  bundle: true,
  format: "esm",
  outfile: out,
  alias: { "@": resolve(root, "src") },
});
const { classifyField, resolveValue, resolvePhoneCountry } = await import(pathToFileURL(out).href);

const sig = (label, extra = {}) => ({ label, name: "", id: "", autocomplete: "", inputType: "text", ...extra });
const ctx = (answers = {}, candidate = {}) => ({
  candidate: { first_name: "Jane", last_name: "Doe", full_name: "Jane Doe", email: "j@x.com", phone: "5550100", location: null, linkedin_url: null, ...candidate },
  answers,
  learned_answers: {},
});

test("preferred first name is its own field, not the legal first name", () => {
  assert.deepEqual(classifyField(sig("Preferred First Name")), { kind: "canonical", key: "preferred_name" });
  assert.deepEqual(classifyField(sig("First Name")), { kind: "canonical", key: "first_name" });
  assert.equal(resolveValue("preferred_name", ctx({}, { preferred_name: "Janie" }), []), "Janie");
  assert.equal(resolveValue("preferred_name", ctx(), []), "Jane");
});

test("phone country fields are recognized, plain country is not", () => {
  assert.deepEqual(classifyField(sig("Phone Country Code")), { kind: "canonical", key: "phone_country" });
  assert.deepEqual(classifyField(sig("Country code")), { kind: "canonical", key: "phone_country" });
  assert.deepEqual(classifyField(sig("Mobile country")), { kind: "canonical", key: "phone_country" });
  assert.deepEqual(classifyField(sig("Phone")), { kind: "canonical", key: "phone" });
  assert.equal(classifyField(sig("Country")).kind, "unknown");
});

test("phone country resolves to a dial code or the one matching option", () => {
  const us = "United States (+1)";
  assert.equal(resolvePhoneCountry(us, []), "+1");
  assert.equal(resolvePhoneCountry(us, ["Canada +1", "United States +1", "United Kingdom +44"]), "United States +1");
  assert.equal(resolvePhoneCountry(us, ["United States Minor Outlying Islands +1", "United States +1"]), "United States +1");
  assert.equal(resolvePhoneCountry(us, ["Canada +1", "Bahamas +1"]), null);
  assert.equal(resolvePhoneCountry(undefined, []), null);
  assert.equal(resolveValue("phone_country", ctx({}), []), null);
});

test("a 'City, ST' location expands to the full entry a place list shows", async () => {
  const { expandLocation } = await import(pathToFileURL(out).href);
  assert.deepEqual(expandLocation("Boston, MA"), {
    typeText: "Boston",
    alternates: ["Boston, Massachusetts, United States", "Boston, Massachusetts"],
  });
  assert.equal(expandLocation("Boston")?.typeText, undefined);
  assert.equal(expandLocation("Paris, FR"), null);
});

test("willingness questions use the person's saved yes/no, and history questions are left alone", () => {
  const q = {
    bg: "Are you willing to submit to a background check? Cardinal Health will conduct a background check only where legally permissible.",
    crim: "Are you willing to submit to a criminal record check? We will conduct a criminal record check only where legally permissible.",
    drug: "Are you willing to complete a drug screen and/or medical examination?",
    random: "Are you willing to take a random drug test if employed?",
    age: "Are you 18 years of age or older? (Applicants under age 18 will be required to submit documentation)",
  };
  assert.deepEqual(classifyField(sig(q.bg)), { kind: "canonical", key: "background_check" });
  assert.deepEqual(classifyField(sig(q.crim)), { kind: "canonical", key: "criminal_check" });
  assert.deepEqual(classifyField(sig(q.drug)), { kind: "canonical", key: "drug_screen" });
  assert.deepEqual(classifyField(sig(q.random)), { kind: "canonical", key: "drug_screen" });
  assert.deepEqual(classifyField(sig(q.age)), { kind: "canonical", key: "age_18" });
  // Questions about the past are never answered for the person.
  assert.equal(classifyField(sig("Have you ever failed a drug test?")).kind, "unknown");
  assert.equal(classifyField(sig("Have you ever been convicted of a crime? A criminal record check may follow.")).kind, "unknown");
  const answers = { background_check_ok: true, criminal_check_ok: true, drug_screen_ok: false, age_18_plus: true };
  assert.equal(resolveValue("background_check", ctx(answers), ["Select One", "Yes", "No"]), "Yes");
  assert.equal(resolveValue("drug_screen", ctx(answers), ["Select One", "Yes", "No"]), "No");
  assert.equal(resolveValue("age_18", ctx(answers), ["Yes", "No"]), "Yes");
  // Nothing saved: left for the person.
  assert.equal(resolveValue("criminal_check", ctx({}), ["Yes", "No"]), null);
});

test("years of experience and highest education come from the saved profile", () => {
  assert.deepEqual(classifyField(sig("Please indicate how many years of experience you have in the field in which you are applying.")), { kind: "canonical", key: "years_experience" });
  assert.deepEqual(classifyField(sig("Please indicate your highest level of education")), { kind: "canonical", key: "highest_education" });
  // One tool or skill is not the whole field.
  assert.equal(classifyField(sig("How many years of experience do you have with SQL?")).kind, "unknown");
  const c = {
    ...ctx(),
    experience: [
      { start_date: "2014-06", end_date: "2018-05", current: false },
      { start_date: "2017-01", end_date: "2019-12", current: false }, // overlaps: counted once
      { start_date: "2021-03", end_date: null, current: true },
    ],
    education: [
      { degree: "Bachelor's Degree", end_date: "2014-05" },
      { degree: "Master's Degree", end_date: "2099-05" }, // not finished yet
    ],
  };
  const years = ["Select One", "No Experience", "Less than 1 year", "1-3 years", "3-6 years", "6-10 years", "10+ years"];
  assert.equal(resolveValue("years_experience", c, years), "10+ years");
  const levels = ["Select One", "Professional Certificate", "Bachelor’s / College Degree (3 or 4 years)", "Master’s Degree", "Doctoral Degree"];
  assert.equal(resolveValue("highest_education", c, levels), "Bachelor’s / College Degree (3 or 4 years)");
  assert.equal(resolveValue("years_experience", ctx(), years), null); // nothing saved: left for the person
});


test("relocation, desired salary and start date use the person's saved answers", () => {
  assert.deepEqual(classifyField(sig("Would you be interested in relocating?")), { kind: "canonical", key: "relocation" });
  assert.equal(classifyField(sig("Do you need relocation assistance?")).kind, "unknown");
  assert.deepEqual(classifyField(sig("What is your desired salary range?")), { kind: "canonical", key: "desired_salary" });
  assert.deepEqual(classifyField(sig("When would you be available to start?")), { kind: "canonical", key: "start_availability" });
  assert.equal(classifyField(sig("When would you be available to start?", { inputType: "date" })).kind, "unknown");
  const answers = { relocation_ok: false, desired_salary: "$90,000 to $110,000", available_to_start: "Two weeks after an offer" };
  assert.equal(resolveValue("relocation", ctx(answers), ["Select One", "Yes", "No"]), "No");
  assert.equal(resolveValue("relocation", ctx(), ["Select One", "Yes", "No"]), null); // nothing saved, never guessed
  assert.equal(resolveValue("desired_salary", ctx(answers), []), "$90,000 to $110,000");
  assert.equal(resolveValue("start_availability", ctx(answers), []), "Two weeks after an offer");
  assert.equal(resolveValue("start_availability", ctx(), []), null);
});
