/** Shapes shared between the service worker, the injected fill script and the popup. */

export interface ApplyCandidate {
  first_name: string;
  preferred_name?: string | null;
  recent_title?: string | null;
  recent_employer?: string | null;
  last_name: string;
  full_name: string;
  email: string;
  phone: string | null;
  location: string | null;
  linkedin_url: string | null;
}

export interface ApplyExperience {
  title: string;
  employer: string;
  location?: string | null;
  /** "YYYY-MM" */
  start_date?: string | null;
  end_date?: string | null;
  current: boolean;
  /** The role's bullets from the resume used for this job (tailored, else original), one per line. */
  description: string;
}

export interface ApplyEducation {
  institution: string;
  degree?: string | null;
  degree_short?: string | null;
  field?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  gpa?: string | null;
}

export interface ApplyCertification {
  name: string;
  issuer?: string | null;
  /** "YYYY-MM-DD" */
  issued?: string | null;
  expires?: string | null;
}

export interface ApplyContext {
  candidate: ApplyCandidate;
  answers: Record<string, unknown>;
  learned_answers: Record<string, string>;
  experience?: ApplyExperience[];
  education?: ApplyEducation[];
  /** Skills for a skills box, those named in the job posting first. */
  skills?: string[];
  certifications?: ApplyCertification[];
}

export interface FlaggedField {
  label: string;
  field_type: string;
  options: string[];
  required: boolean;
}

export interface FillReport {
  /** Labels of the fields that were filled (never their values). */
  filled: string[];
  /** Required (or answerable) questions left blank for the candidate. */
  flagged: FlaggedField[];
  /** Optional fields the engine did not recognize and left alone. */
  leftBlank: number;
  /** Fields that already had something typed in, which are never overwritten. */
  alreadyFilled: number;
  /** Voluntary self-identification questions, never touched. */
  voluntarySkipped: number;
  /** Workday only: pages moved past automatically, and why it stopped. */
  pagesAdvanced?: number;
  stoppedBecause?: string;
}
