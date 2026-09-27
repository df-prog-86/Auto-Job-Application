/**
 * ATS adapter interface (spec §35). No implementations yet — Greenhouse and
 * Lever land in Milestone 7, the generic fallback in Milestone 6, Workday
 * in Milestone 9. This file exists now so the interface shape is fixed
 * before any adapter is written against it, and so the form engine
 * (src/form-engine/, also not yet implemented) has a stable contract to
 * target.
 */

export type PageState =
  | "SIGN_IN"
  | "CREATE_ACCOUNT"
  | "RESUME_UPLOAD"
  | "CONTACT_INFORMATION"
  | "WORK_EXPERIENCE"
  | "EDUCATION"
  | "APPLICATION_QUESTIONS"
  | "VOLUNTARY_DISCLOSURES"
  | "REVIEW"
  | "SUBMIT"
  | "CANDIDATE_HOME"
  | "UNKNOWN";

export interface Field {
  domSignature: string;
  label: string;
  fieldType:
    | "text"
    | "email"
    | "tel"
    | "textarea"
    | "select"
    | "checkbox"
    | "radio"
    | "date"
    | "number"
    | "multiselect"
    | "combobox"
    | "file";
  required: boolean;
  options?: string[];
}

export interface FieldMappingResult {
  field: Field;
  canonicalField: string;
  confidence: number;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export interface SubmissionResult {
  verified: boolean;
  confirmationId?: string;
  confirmationText?: string;
  finalUrl?: string;
}

export interface ATSAdapter {
  detect(): boolean;
  initialize(): Promise<void>;
  detectPage(): PageState;
  discoverFields(): Promise<Field[]>;
  mapFields(): Promise<FieldMappingResult[]>;
  uploadResume(): Promise<void>;
  processQuestions(): Promise<void>;
  validatePage(): Promise<ValidationResult>;
  nextPage(): Promise<void>;
  canSubmit(): Promise<boolean>;
  submit(): Promise<void>;
  verifySubmission(): Promise<SubmissionResult>;
}
