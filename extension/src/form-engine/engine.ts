/**
 * Fills the application page in front of the candidate. The rules, in order
 * of importance:
 *   1. Never submit or send anything (see safety.ts).
 *   2. Never overwrite something the candidate already typed.
 *   3. Never guess: if a value is not known for certain, leave the field
 *      blank and report it so it shows up on the Needs Attention page.
 *   4. Never touch voluntary self-identification questions.
 */

import { classifyField, expandLocation, learnedAnswer, normalizeQuestion, phoneCountryName, resolveValue, resolveVoluntary } from "@/form-engine/canonical";
import type { Classification } from "@/form-engine/canonical";
import { discoverFields } from "@/form-engine/discover";
import type { FormField } from "@/form-engine/discover";
import type { ComboboxHints } from "@/form-engine/fill";
import { base64ToFile, currentValue, fillField, fillFile, readComboboxOptions, readDropdownOptions } from "@/form-engine/fill";
import { clearMarks, mark, showBanner } from "@/form-engine/highlight";
import type { ApplyContext, FillReport } from "@/form-engine/types";

/** Questions that grant consent or accept terms are never answered for the candidate. */
const CONSENT = /\b(terms|privacy|agree|agreement|consent|acknowledg\w*|certif\w*|authori[sz]e us|authori[sz]e such|investigation|background check|policy)\b/i;

export interface ResumePayload {
  base64: string;
  filename: string;
}

export async function fillPage(
  doc: Document,
  ctx: ApplyContext,
  resume: ResumePayload | null,
): Promise<FillReport> {
  clearMarks(doc);
  const report: FillReport = { filled: [], flagged: [], leftBlank: 0, alreadyFilled: 0, voluntarySkipped: 0 };

  const fields = discoverFields(doc);
  for (const [index, field] of fields.entries()) {
    // A bare "Country" box sitting right before the phone box is the phone's country code.
    const next = fields[index + 1];
    const beforePhone =
      !!next &&
      normalizeQuestion(field.label) === "country" &&
      (next.inputType === "tel" || /phone|mobile/i.test(`${next.label} ${next.name} ${next.id}`));
    const sig = {
      label: beforePhone ? "Phone country" : field.label,
      name: field.name,
      id: field.id,
      autocomplete: field.autocomplete,
      inputType: field.inputType,
    };
    const cls: Classification = classifyField(sig);

    if (cls.kind === "voluntary") {
      // Only ever answered from what the person chose on their Profile; otherwise left alone.
      const known = ["gender", "race", "hispanic", "veteran"].includes(cls.topic);
      if (known && field.kind !== "checkbox" && currentValue(field) === "") {
        let choices = field.options;
        if (field.kind === "dropdown") choices = await readDropdownOptions(field.el);
        if (field.kind === "combobox") choices = await readComboboxOptions(field.el as HTMLInputElement);
        const pick = resolveVoluntary(cls.topic, ctx.answers, choices);
        if (pick && (await fillField(field, pick))) {
          done(report, field);
          continue;
        }
      }
      report.voluntarySkipped++;
      continue;
    }
    if (field.kind === "checkbox") {
      // Consent and acknowledgement boxes are always the candidate's own click.
      if (field.required) flag(report, field);
      continue;
    }
    if (field.kind === "yesno" && CONSENT.test(field.label)) {
      // Agreeing to terms is always the candidate's own click, even when it is drawn as Yes/No buttons.
      if (field.required) flag(report, field);
      continue;
    }
    if (currentValue(field) !== "") {
      report.alreadyFilled++;
      continue;
    }

    if (cls.kind === "canonical" && cls.key === "resume") {
      if (field.kind === "file" && resume && fillFile(field, base64ToFile(resume.base64, resume.filename))) {
        done(report, field);
      } else if (field.required) {
        flag(report, field);
      } else {
        report.leftBlank++;
      }
      continue;
    }

    if (field.kind === "file") {
      if (field.required) flag(report, field);
      else report.leftBlank++;
      continue;
    }

    let options = field.options;
    if (field.kind === "combobox" && cls.kind !== "canonical") {
      options = []; // free-text style lookups are tried by typing, not by reading the menu
    }
    if (field.kind === "dropdown") {
      // Dropdown buttons only show their choices once opened; read them so a value is matched exactly, never guessed.
      options = cls.kind === "canonical" || cls.kind === "unknown" ? await readDropdownOptions(field.el) : [];
      if (options.length === 0 && cls.kind === "canonical" && cls.key === "phone_country") options = ["(unreadable)"];
    }
    if (field.kind === "combobox" && cls.kind === "canonical" && ["sponsorship", "work_authorization", "security_clearance", "phone_country"].includes(cls.key)) {
      options = await readComboboxOptions(field.el as HTMLInputElement);
      // A dropdown whose choices could not be read is never answered from a bare code.
      if (options.length === 0 && cls.key === "phone_country") options = ["(unreadable)"];
    }

    const value =
      cls.kind === "canonical"
        ? resolveValue(cls.key, ctx, options)
        : learnedAnswer(field.label, ctx, field.kind === "select" || field.kind === "radio" || field.kind === "yesno" || field.kind === "dropdown" ? options : []);

    let hints: ComboboxHints | undefined;
    if (cls.kind === "canonical" && cls.key === "phone_country") {
      const name = phoneCountryName(ctx.answers["phone_country"]);
      if (name) hints = { typeText: name };
    } else if (cls.kind === "canonical" && cls.key === "location" && value) {
      const place = expandLocation(value);
      if (place) hints = place;
    }
    if (value && (await fillField(field, value, hints))) {
      done(report, field);
    } else if (field.required || cls.kind === "canonical") {
      flag(report, field);
    } else {
      report.leftBlank++;
    }
  }

  showBanner(doc, report.filled.length, report.flagged.length);
  return report;
}

function done(report: FillReport, field: FormField): void {
  report.filled.push(field.label);
  mark(field.outlineEl, "filled");
}

function flag(report: FillReport, field: FormField): void {
  report.flagged.push({
    label: field.label,
    field_type: field.kind === "radio" ? "radio" : field.kind,
    options: field.options.slice(0, 50),
    required: field.required,
  });
  mark(field.outlineEl, "flagged");
}
