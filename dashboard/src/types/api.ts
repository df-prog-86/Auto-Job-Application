/**
 * Hand-written for Milestone 1, mirroring the backend's Pydantic response
 * models (app/api/system.py, app/api/automation.py). Per spec §5, these
 * should be generated from FastAPI's OpenAPI schema instead of hand-kept in
 * sync — that generation step (`openapi-typescript` or similar) is wired up
 * once the backend is actually running and its schema is reachable; this
 * file is the interim source of truth until then.
 */

export interface HealthResponse {
  status: string;
  time: string;
}

export interface VersionResponse {
  backend_version: string;
  api_version: string;
  schema_version: string;
}

export type AutomationMode = "PAUSED" | "REVIEW" | "AUTO";

export interface AutomationStatusResponse {
  mode: AutomationMode;
}

export interface PairingSecretResponse {
  pairing_secret: string;
  expires_note: string;
}

export interface PairRequest {
  pairing_secret: string;
  extension_origin: string;
}

export interface PairResponse {
  extension_token: string;
}

// --- Profile / onboarding (mirrors backend/app/schemas/profile.py) ---------

export interface ContactInfo {
  name: string;
  preferred_name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  linkedin_url?: string | null;
  portfolio_urls: string[];
}

export interface EmploymentEntry {
  employer: string;
  title: string;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
  source_text: string;
}

export interface EducationEntry {
  institution: string;
  degree?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface CertificationEntry {
  certification: string;
  issuer?: string | null;
  date?: string | null;
  expiration?: string | null;
}

export interface ProjectEntry {
  name: string;
  description?: string | null;
  technologies: string[];
  source_text?: string | null;
}

export interface ResumeExtraction {
  contact: ContactInfo;
  employment: EmploymentEntry[];
  education: EducationEntry[];
  skills: string[];
  certifications: CertificationEntry[];
  projects: ProjectEntry[];
}

export interface DraftClaim {
  category: string;
  canonical_text: string;
  employer?: string | null;
  associated_role?: string | null;
  skills: string[];
  start_date?: string | null;
  end_date?: string | null;
  metrics: Record<string, unknown>;
  source_section: string;
  source_text: string;
}

export interface ResumeParseResponse {
  extracted_text_preview: string;
  used_ocr: boolean;
  extraction: ResumeExtraction;
  draft_claims: DraftClaim[];
}

export interface EmploymentHistoryOut {
  id: number;
  employer: string;
  title: string;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
}

export interface EducationOut {
  id: number;
  institution: string;
  degree?: string | null;
  degree_short?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  gpa?: string | null;
}

export interface SkillOut {
  id: number;
  canonical_skill: string;
  candidate_confirmed: boolean;
}

export interface CertificationOut {
  id: number;
  certification: string;
  issuer?: string | null;
  date?: string | null;
  expiration?: string | null;
}

export interface VerifiedClaimSummaryOut {
  category: string;
  canonical_text: string;
}

export interface ProfileOut {
  id: number;
  name: string;
  preferred_name?: string | null;
  email: string;
  phone?: string | null;
  location?: string | null;
  linkedin_url?: string | null;
  portfolio_urls: string[];
  employment_history: EmploymentHistoryOut[];
  education: EducationOut[];
  skills: SkillOut[];
  certifications: CertificationOut[];
  verified_claims: VerifiedClaimSummaryOut[];
}

// --- Search profiles / discovery (mirrors backend/app/schemas/discovery.py) -

export interface SearchProfile {
  id: number;
  name: string;
  titles: string[];
  locations: string[];
  remote: boolean;
  hybrid: boolean;
  onsite: boolean;
  salary_minimum?: number | null;
  employment_type?: string | null;
  desired_seniority: string[];
  excluded_titles: string[];
  excluded_employers: string[];
  excluded_industries: string[];
  required_keywords: string[];
  preferred_keywords: string[];
  travel_preference?: string | null;
  relocation_willingness: boolean;
  enabled: boolean;
}

export type SearchProfileInput = Omit<SearchProfile, "id">;

export interface TargetEmployer {
  id: number;
  name: string;
  ats: string;
  identifier: string;
  enabled: boolean;
  notes?: string | null;
  last_checked_at?: string | null;
  last_check_status?: string | null;
  last_check_error?: string | null;
}

export interface TargetEmployerInput {
  name: string;
  ats: string;
  identifier: string;
  enabled?: boolean;
  notes?: string | null;
}

export interface JobEvaluationOut {
  overall_score: number;
  summary: string;
  gaps: string[];
  model_used?: string | null;
  evaluation_version: string;
}

export type ApplicationStatus = "not_started" | "proceeding";

export interface GeneratedDocumentOut {
  id: number;
  document_type: string;
  format: string;
  generated_at: string;
  template_version?: string;
}

export interface TailorResumeOut {
  documents: GeneratedDocumentOut[];
  used_original_wording: boolean;
  problems: string[];
  changelog: string[];
}

export interface JobOut {
  id: number;
  ats?: string | null;
  company: string;
  title: string;
  location?: string | null;
  remote_type?: string | null;
  salary: Record<string, unknown>;
  canonical_application_url: string;
  first_seen: string;
  last_seen: string;
  status: string;
  application_status: ApplicationStatus;
  evaluation?: JobEvaluationOut | null;
  documents: GeneratedDocumentOut[];
  already_existed?: boolean;
}

export interface JobDetailOut extends JobOut {
  description?: string | null;
}

export interface ManualJobInput {
  url: string;
}

export interface DiscoveryRunResult {
  employers_checked: number;
  employers_failed: number;
  postings_fetched: number;
  postings_matched: number;
  jobs_created: number;
  jobs_updated: number;
  errors: string[];
}


export interface AnswerOut {
  answer_key: string;
  value_type: string;
  value: unknown;
  explanatory_text?: string | null;
  provenance?: string | null;
  user_confirmed: boolean;
}

export interface AnswerUpsert {
  value_type: "bool" | "str" | "number" | "date";
  value: unknown;
  explanatory_text?: string | null;
  user_confirmed?: boolean;
}

export interface MasterRole {
  context: string;
  bullets: string[];
}

export interface EmploymentInput {
  employer?: string | null;
  title?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
}

export interface EducationInput {
  institution?: string | null;
  degree?: string | null;
  degree_short?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  gpa?: string | null;
}

export interface CertificationInput {
  certification?: string | null;
  issuer?: string | null;
  date?: string | null;
  expiration?: string | null;
}

export interface ProfileUpdate {
  name?: string;
  preferred_name?: string | null;
  email?: string;
  phone?: string | null;
  location?: string | null;
  linkedin_url?: string | null;
}

export interface PendingQuestionOut {
  id: number;
  job_id: number;
  job_title: string;
  company: string;
  label: string;
  field_type: string;
  options: string[];
  required: boolean;
  status: string;
  answer_text?: string | null;
}

export interface JobSearchCriteria {
  titles: string;
  location?: string | null;
  work_type: "any" | "remote" | "hybrid" | "onsite";
  keywords?: string | null;
  exclude_companies?: string | null;
  target_salary?: number | null;
  require_salary: boolean;
  posted_within_days: 0 | 7 | 14 | 30;
  count: number;
}

export interface JobSearchResultOut {
  id: number;
  title: string;
  company: string;
  location?: string | null;
  work_type?: string | null;
  salary_text?: string | null;
  summary?: string | null;
  url: string;
  grounded: boolean;
  status: string;
}

export interface JobSearchRunOut {
  found: number;
  skipped: number;
  results: JobSearchResultOut[];
}

export interface AddSearchResultOut {
  job: JobOut;
  from_summary: boolean;
}
