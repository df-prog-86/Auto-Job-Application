import type {
  AnswerOut,
  AnswerUpsert,
  AutomationStatusResponse,
  DiscoveryRunResult,
  CertificationInput,
  EducationInput,
  EmploymentInput,
  HealthResponse,
  AddSearchResultOut,
  JobDetailOut,
  JobSearchCriteria,
  JobSearchResultOut,
  JobSearchRunOut,
  JobOut,
  ManualJobInput,
  MasterRole,
  PairingSecretResponse,
  PendingQuestionOut,
  PairRequest,
  PairResponse,
  ProfileOut,
  ProfileUpdate,
  ResumeExtraction,
  ResumeParseResponse,
  GeneratedDocumentOut,
  TailorResumeOut,
  SearchProfile,
  SearchProfileInput,
  TargetEmployer,
  TargetEmployerInput,
  VersionResponse,
} from "@/types/api";

/**
 * Same-origin in production (backend serves the dashboard at /app and the
 * API at /api/v1 from the same process — spec §14), proxied in dev by
 * vite.config.ts. Never hits anything but 127.0.0.1.
 */
const API_BASE = "/api/v1";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: isFormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail ?? JSON.stringify(body);
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  version: () => request<VersionResponse>("/version"),

  automationStatus: () => request<AutomationStatusResponse>("/automation/status"),
  startAutomation: () =>
    request<AutomationStatusResponse>("/automation/start", { method: "POST" }),
  pauseAutomation: () =>
    request<AutomationStatusResponse>("/automation/pause", { method: "POST" }),

  createPairingSecret: () =>
    request<PairingSecretResponse>("/system/pairing-secret", { method: "POST" }),
  pairExtension: (payload: PairRequest) =>
    request<PairResponse>("/system/pair", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  parseResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ResumeParseResponse>("/profile/resume/parse", {
      method: "POST",
      body: form,
    });
  },
  commitProfile: (payload: {
    extraction: ResumeExtraction;
    approved_claims: ResumeParseResponse["draft_claims"];
    resume_filename: string;
  }) =>
    request<ProfileOut>("/profile/commit", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getProfile: () => request<ProfileOut>("/profile"),
  updateProfile: (payload: ProfileUpdate) =>
    request<ProfileOut>("/profile", { method: "PATCH", body: JSON.stringify(payload) }),
  masterRoles: () => request<MasterRole[]>("/profile/master/roles"),
  addEmployment: (payload: EmploymentInput) =>
    request<ProfileOut>("/profile/employment", { method: "POST", body: JSON.stringify(payload) }),
  updateEmployment: (id: number, payload: EmploymentInput) =>
    request<ProfileOut>(`/profile/employment/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteEmployment: (id: number) => request<ProfileOut>(`/profile/employment/${id}`, { method: "DELETE" }),
  addEducation: (payload: EducationInput) =>
    request<ProfileOut>("/profile/education", { method: "POST", body: JSON.stringify(payload) }),
  updateEducation: (id: number, payload: EducationInput) =>
    request<ProfileOut>(`/profile/education/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteEducation: (id: number) => request<ProfileOut>(`/profile/education/${id}`, { method: "DELETE" }),
  addCertification: (payload: CertificationInput) =>
    request<ProfileOut>("/profile/certifications", { method: "POST", body: JSON.stringify(payload) }),
  updateCertification: (id: number, payload: CertificationInput) =>
    request<ProfileOut>(`/profile/certifications/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCertification: (id: number) => request<ProfileOut>(`/profile/certifications/${id}`, { method: "DELETE" }),
  addSkill: (canonical_skill: string) =>
    request<ProfileOut>("/profile/skills", { method: "POST", body: JSON.stringify({ canonical_skill }) }),
  deleteSkill: (id: number) => request<ProfileOut>(`/profile/skills/${id}`, { method: "DELETE" }),

  listSearchProfiles: () => request<SearchProfile[]>("/search-profiles"),
  createSearchProfile: (payload: SearchProfileInput) =>
    request<SearchProfile>("/search-profiles", { method: "POST", body: JSON.stringify(payload) }),
  updateSearchProfile: (id: number, payload: Partial<SearchProfileInput>) =>
    request<SearchProfile>(`/search-profiles/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteSearchProfile: (id: number) =>
    request<void>(`/search-profiles/${id}`, { method: "DELETE" }),

  listTargetEmployers: () => request<TargetEmployer[]>("/discovery/employers"),
  addTargetEmployer: (payload: TargetEmployerInput) =>
    request<TargetEmployer>("/discovery/employers", { method: "POST", body: JSON.stringify(payload) }),
  deleteTargetEmployer: (id: number) =>
    request<void>(`/discovery/employers/${id}`, { method: "DELETE" }),
  runDiscovery: () => request<DiscoveryRunResult>("/discovery/run", { method: "POST" }),

  listJobs: () => request<JobOut[]>("/jobs"),
  getJob: (id: number) => request<JobDetailOut>(`/jobs/${id}`),
  addJobByUrl: (payload: ManualJobInput) =>
    request<JobOut>("/jobs/manual", { method: "POST", body: JSON.stringify(payload) }),
  requalifyJob: (id: number) => request<JobOut>(`/jobs/${id}/qualify`, { method: "POST" }),
  masterStatus: () => request<{ saved: boolean; updated_at: string | null }>("/profile/master"),
  undoProceed: (id: number) => request<JobOut>(`/jobs/${id}/unproceed`, { method: "POST" }),
  markApplied: (id: number, appliedOn?: string) =>
    request<JobOut>(`/jobs/${id}/applied`, {
      method: "POST",
      body: JSON.stringify(appliedOn ? { applied_on: appliedOn } : {}),
    }),
  draftFollowUp: (id: number, kind: "after_applying" | "after_interview" = "after_applying") =>
    request<{ subject: string; body: string }>(`/jobs/${id}/follow-up-draft`, {
      method: "POST",
      body: JSON.stringify({ kind }),
    }),
  markNotApplied: (id: number) => request<JobOut>(`/jobs/${id}/unapplied`, { method: "POST" }),
  deleteJob: (id: number) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  listAnswers: () => request<AnswerOut[]>("/profile/answers"),
  saveAnswer: (key: string, payload: AnswerUpsert) =>
    request<AnswerOut>(`/profile/answers/${key}`, { method: "PUT", body: JSON.stringify(payload) }),
  listSearchResults: () =>
    request<JobSearchRunOut>("/job-search/results").then((r) => r.results as JobSearchResultOut[]),
  runJobSearch: (criteria: JobSearchCriteria) =>
    request<JobSearchRunOut>("/job-search/run", { method: "POST", body: JSON.stringify(criteria) }),
  scoreSearchResult: (id: number) =>
    request<JobSearchResultOut>(`/job-search/results/${id}/score`, { method: "POST" }),
  addSearchResult: (id: number) =>
    request<AddSearchResultOut>(`/job-search/results/${id}/add`, { method: "POST" }),
  removeSearchResult: (id: number) =>
    request<JobSearchResultOut>(`/job-search/results/${id}/remove`, { method: "POST" }),
  clearSearchResults: () => request<{ cleared: number }>("/job-search/clear", { method: "POST" }),
  clearQuestions: (ids?: number[]) =>
    request<{ cleared: number }>("/needs-attention/clear", { method: "POST", body: JSON.stringify(ids ? { ids } : {}) }),
  forgetAnswer: (key: string) => request<void>(`/profile/answers/${encodeURIComponent(key)}`, { method: "DELETE" }),
  useOriginalResume: (id: number) =>
    request<GeneratedDocumentOut[]>(`/jobs/${id}/original-resume`, { method: "POST" }),
  tailorResume: (id: number) =>
    request<TailorResumeOut>(`/jobs/${id}/tailor`, { method: "POST" }),
  listNeedsAttention: () => request<PendingQuestionOut[]>("/needs-attention"),
  answerQuestion: (id: number, answer: string) =>
    request<PendingQuestionOut>(`/needs-attention/${id}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  dismissQuestion: (id: number) =>
    request<PendingQuestionOut>(`/needs-attention/${id}/dismiss`, { method: "POST" }),
  proceedWithApplication: (id: number) =>
    request<JobOut>(`/jobs/${id}/proceed`, { method: "POST" }),
};

export const documentDownloadUrl = (documentId: number) =>
  `${API_BASE}/jobs/documents/${documentId}/download`;

export { ApiError };
