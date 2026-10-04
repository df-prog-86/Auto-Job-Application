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
