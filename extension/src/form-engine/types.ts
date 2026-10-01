/** Shapes shared between the service worker, the injected fill script and the popup. */

export interface ApplyCandidate {
  first_name: string;
  preferred_name?: string | null;
  last_name: string;
  full_name: string;
  email: string;
  phone: string | null;
  location: string | null;
  linkedin_url: string | null;
}

export interface ApplyContext {
  candidate: ApplyCandidate;
  answers: Record<string, unknown>;
  learned_answers: Record<string, string>;
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
}
