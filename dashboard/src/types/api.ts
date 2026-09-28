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
  employer: string;
  title: string;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
}

export interface EducationOut {
  institution: string;
  degree?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface SkillOut {
  canonical_skill: string;
  candidate_confirmed: boolean;
}

export interface CertificationOut {
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

