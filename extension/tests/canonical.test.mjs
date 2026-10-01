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
