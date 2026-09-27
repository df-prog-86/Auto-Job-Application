Autonomous Job Application Platform



Production Engineering Specification — Version 1.0



Specification date: September 26, 2026



1. Objective



Build a local-first automated job application platform that can take a user from initial resume upload through job discovery, qualification, tailored-resume generation, ATS account creation/login, application completion, submission, verification, and application tracking with minimal human intervention.



The user-facing experience must remain simple:



1. Install the local application and Chrome extension.

2. Upload a resume.

3. Review extracted profile information.

4. Answer a small set of application and job-search questions.

5. Set job preferences.

6. Enable automation.

7. Review exceptions only when necessary.

8. View every application in a clean dashboard.

9. Export the complete application history to Excel or CSV.



The architecture must strictly separate:



* Orchestration, candidate intelligence, AI, storage, and job discovery: Python backend.

* Browser execution: Chrome Manifest V3 extension.

* End-user interface: React dashboard.

* Durable system state: SQLite.

* Credentials: operating-system credential store.



The Chrome extension is the browser execution layer, not the primary application.



⸻



2. Core Engineering Principles



The implementation must follow these principles.



2.1 Local-first



Candidate data, application history, credentials, generated resumes, job records, and system state should remain on the user’s computer unless an external service must receive data to perform a specific function.



External model providers should receive only the minimum information required for the requested AI operation.



2.2 Deterministic before generative



Use deterministic software for:



* job normalization;

* eligibility filters;

* state management;

* ATS detection;

* field mapping;

* stored question answers;

* salary/work authorization/sponsorship responses;

* account management;

* navigation;

* document rendering;

* validation;

* submission;

* tracking;

* spreadsheet generation.



Use LLMs only when interpretation or controlled generation materially improves the result.



Primary LLM uses:



* structured resume extraction;

* job-requirement extraction;

* ambiguous question classification;

* candidate-evidence retrieval assistance;

* evidence-grounded open-text answers;

* resume tailoring;

* final qualification sanity checks where useful.



2.3 Candidate truth is authoritative



No model may invent:



* employers;

* responsibilities;

* technologies;

* accomplishments;

* metrics;

* dates;

* degrees;

* certifications;

* security clearances;

* citizenship;

* work authorization;

* years of experience;

* salary expectations;

* demographic information.



Every generated factual claim must trace to an approved VerifiedClaim or an explicit candidate answer.



2.4 ATS-specific execution



Do not attempt to create one universal DOM script.



Use:



* ATS-specific adapters;

* shared form-mapping utilities;

* a generic fallback adapter.



2.5 Durable execution



The platform must recover correctly after:



* browser restart;

* extension service-worker termination;

* backend restart;

* tab crash;

* temporary network outage;

* ATS timeout;

* model-provider failure.



Never rely on an in-memory JavaScript variable as the authoritative state of an application.



2.6 Respect external controls



The platform must not attempt to bypass:



* CAPTCHA;

* MFA;

* access controls;

* rate limits;

* platform application limits;

* security challenges;

* explicit anti-automation controls.



When encountered, pause the affected application or provider and request appropriate user action.



Do not build randomized “humanization” logic intended to evade detection.



⸻



3. Verified External Platform Constraints



These constraints must be reflected in the implementation.



Chrome Manifest V3 service workers are intentionally ephemeral. Chrome normally terminates an extension service worker after approximately 30 seconds of inactivity, and Chrome specifically recommends persisting state rather than relying on globals or ordinary timers. Chrome alarms are the appropriate mechanism for periodic extension work. (Chrome for Developers⁠￼)



Programmatic script injection requires the scripting permission plus suitable host permissions or temporary activeTab access. Because this platform opens and automates background ATS tabs itself, explicit ATS host permissions—not activeTab alone—must support the automated path. (Chrome for Developers⁠￼)



Workday Candidate Home may be configured as mandatory. Workday uses the candidate’s email as the Candidate Home identifier, tenant-specific password requirements can apply, and returning candidates may be offered “Use my last application” or upload a new resume. (Workday Documentation⁠￼)



Do not assume candidate-side access to Greenhouse or Lever submission APIs. Greenhouse job-board application integrations require an employer-created API credential, and Lever’s programmatic application POST requires an API key generated for the employer’s Lever account. The normal consumer application path is therefore browser interaction with the employer’s application form. (Greenhouse Support⁠￼)



LinkedIn currently prohibits third-party software or browser extensions that scrape or automate activity on LinkedIn. Indeed currently prohibits unauthorized automation of Indeed Apply. Therefore, do not implement direct automated application submission on either surface. Route users to supported employer ATS pages when appropriate. (LinkedIn⁠￼)



Greenhouse employers can configure candidate application-frequency rules. The platform therefore needs employer-specific application governance in addition to a global daily limit. (Greenhouse Support⁠￼)



⸻



4. Target User Experience



The product must expose six primary user areas.



4.1 Home



Display:



* automation status;

* Start/Pause control;

* applications today;

* applications this week;

* qualified jobs waiting;

* applications needing attention;

* recent submissions;

* recent errors.



Example:



Automation: ACTIVE [Pause]

Applications Today 18

Applications This Week 91

Qualified Jobs Waiting 24

Needs Your Attention 2

Recent Activity

Acme Senior Data Analyst Applied

Contoso Healthcare Analyst Applied

ExampleCo Business Analyst Needs Attention



⸻



4.2 Profile



Support:



* PDF resume upload;

* DOCX resume upload;

* parsed candidate profile;

* employment history;

* education;

* skills;

* certifications;

* verified experience claims;

* contact information;

* application answers.



Users must be able to correct extracted information before enabling automation.



⸻



4.3 Job Preferences



Support one or more search profiles.



Fields should include:



* target job titles;

* desired locations;

* remote;

* hybrid;

* on-site;

* minimum salary;

* employment type;

* desired seniority;

* excluded titles;

* excluded employers;

* excluded industries if desired;

* required keywords;

* optional preferred keywords;

* travel preference;

* relocation willingness.



⸻



4.4 Applications



Provide a spreadsheet-style interactive grid.



Required columns:



* company;

* position;

* location;

* work arrangement;

* salary/range if known;

* qualification score;

* required-qualification coverage;

* date discovered;

* date applied;

* source;

* ATS;

* application status;

* resume used;

* job URL.



Allow:



* search;

* filtering;

* sorting;

* date-range filtering;

* status filtering;

* company filtering;

* exporting;

* opening application detail;

* manually updating downstream status such as Interview or Rejected.



⸻



4.5 Needs Attention



All human intervention should aggregate here.



Examples:



* CAPTCHA;

* MFA;

* email verification;

* unknown legal attestation;

* unknown candidate fact;

* existing account without known password;

* password reset;

* unsupported ATS component;

* ambiguous salary question;

* low-confidence generated answer;

* unresolved required field.



An application must resume automatically after the issue is appropriately resolved.



⸻



4.6 Accounts



Display ATS/employer candidate accounts.



Example:



Acme Corporation Workday Connected

Company B Workday Verification Required

Company C iCIMS Connected



Do not display actual passwords.



⸻



5. Technology Stack



Backend



Use:



* Python 3.11 or newer;

* FastAPI;

* Uvicorn;

* SQLAlchemy 2.x or SQLModel;

* Alembic;

* Pydantic;

* APScheduler;

* httpx;

* PyMuPDF;

* python-docx;

* openpyxl;

* keyring;

* cryptography;

* configurable LLM client using an OpenAI-compatible API;

* optional embedding provider abstraction.



Use uv or another lockfile-based Python dependency manager.



⸻



Frontend



Use:



* React;

* TypeScript;

* Vite;

* Tailwind CSS;

* TanStack Table;

* TanStack Query;

* React Hook Form;

* Zod where useful.



Generate TypeScript API types from FastAPI’s OpenAPI schema rather than manually duplicating backend models.



⸻



Chrome Extension



Use:



* Manifest V3;

* TypeScript;

* bundled local JavaScript only;

* Chrome APIs;

* ATS-specific adapters.



Do not use Selenium or Playwright as the production application runtime.



Playwright may be used in automated testing.



⸻



Database



Use SQLite in WAL mode.



Enable:



* foreign keys;

* transactions;

* migrations;

* indexed lookup fields.



SQLite remains the single source of truth for the local product.



Architect repository abstractions so PostgreSQL could replace SQLite later without redesigning business logic.



⸻



6. Recommended Repository Structure



job-agent/

│

├── backend/

│ ├── app/

│ │ ├── main.py

│ │ ├── config.py

│ │ ├── database.py

│ │ │

│ │ ├── api/

│ │ │ ├── system.py

│ │ │ ├── profile.py

│ │ │ ├── searches.py

│ │ │ ├── jobs.py

│ │ │ ├── applications.py

│ │ │ ├── questions.py

│ │ │ ├── accounts.py

│ │ │ ├── automation.py

│ │ │ └── exports.py

│ │ │

│ │ ├── models/

│ │ ├── schemas/

│ │ ├── repositories/

│ │ ├── services/

│ │ │ ├── onboarding/

│ │ │ ├── discovery/

│ │ │ ├── qualification/

│ │ │ ├── evidence/

│ │ │ ├── llm/

│ │ │ ├── resume/

│ │ │ ├── credentials/

│ │ │ ├── orchestration/

│ │ │ ├── exports/

│ │ │ └── security/

│ │ │

│ │ └── scheduler/

│ │

│ ├── migrations/

│ └── tests/

│

├── dashboard/

│ ├── src/

│ │ ├── pages/

│ │ ├── components/

│ │ ├── hooks/

│ │ ├── api/

│ │ └── types/

│ └── tests/

│

├── extension/

│ ├── manifest.json

│ ├── src/

│ │ ├── service-worker.ts

│ │ ├── content/

│ │ ├── adapters/

│ │ │ ├── base.ts

│ │ │ ├── greenhouse.ts

│ │ │ ├── lever.ts

│ │ │ ├── ashby.ts

│ │ │ ├── workday.ts

│ │ │ └── generic.ts

│ │ ├── form-engine/

│ │ ├── messaging/

│ │ └── security/

│ └── tests/

│

├── shared/

│ ├── schemas/

│ └── fixtures/

│

└── docs/



⸻



7. Configuration



No important product behavior should be hard-coded.



Use a configuration file/environment configuration with settings such as:



APP_ENV=

DATABASE_PATH=

LOCAL_API_PORT=8765

PRIMARY_FAST_MODEL=

FALLBACK_FAST_MODEL=

ESCALATION_MODEL=

EMBEDDING_MODEL=

DISCOVERY_INTERVAL_HOURS=12

DAILY_APPLICATION_TARGET=25

DAILY_APPLICATION_LIMIT=40

WEEKLY_APPLICATION_LIMIT=200

EMPLOYER_WEEKLY_LIMIT=3

MAX_CONCURRENT_APPLICATIONS=1

AUTO_APPLY_MIN_SCORE=

AUTO_APPLY_MIN_REQUIRED_COVERAGE=

AUTO_APPLY_MIN_CONFIDENCE=



Model identifiers must be configurable because model availability and pricing change.



A current inexpensive example is DeepSeek V4.1 Flash through OpenRouter, which supports structured output on compatible provider routes, but production code must verify provider capabilities rather than assume them. (OpenRouter⁠￼)



⸻



8. Secrets and Local Security



8.1 API keys



Never store external API credentials in:



* extension source;

* manifest;

* Chrome storage;

* frontend JavaScript;

* SQLite plaintext.



Store secrets using the OS credential system when possible.



⸻



8.2 Local API



FastAPI must bind only to:



127.0.0.1



Never:



0.0.0.0



unless explicitly running in a controlled development environment.



Every extension request must contain a locally generated authentication token.



The backend must verify:



* authentication token;

* expected origin;

* request schema;

* acceptable Host header;

* reasonable request size.



The production extension origin should be explicitly allowlisted.



⸻



8.3 Pairing



On first run:



1. Backend generates a pairing secret.

2. Extension opens the dashboard pairing route.

3. Backend verifies the extension.

4. Extension receives a persistent local token.

5. Store token in chrome.storage.local restricted to trusted extension contexts.

6. Content scripts must not have direct access to the token.



⸻



8.4 Sensitive profile data



Separate normal candidate data from sensitive disclosure information.



Never infer:



* race;

* ethnicity;

* gender;

* disability;

* veteran status;

* other protected traits.



Only store explicit user responses.



Sensitive disclosure values must never be used in:



* qualification;

* job scoring;

* job ranking;

* resume generation;

* application recommendations.



⸻



9. Database Schema



Implement migrations from the beginning.



CandidateProfile



Store:



* ID;

* name;

* preferred name;

* email;

* phone;

* address/location;

* LinkedIn URL if supplied;

* portfolio URLs;

* created/updated timestamps.



⸻



EmploymentHistory



Store:



* employer;

* title;

* start date;

* end date;

* location;

* source resume ID;

* original resume text.



⸻



Education



Store:



* institution;

* degree;

* field;

* dates;

* source.



⸻



Skills



Store:



* canonical skill;

* aliases;

* explicit candidate confirmation;

* source.



⸻



Certifications



Store:



* certification;

* issuer;

* date;

* expiration if applicable;

* source.



⸻



VerifiedClaims



Each record represents an atomic supported candidate fact.



Fields:



* claim_id;

* category;

* canonical text;

* employer;

* associated role;

* skills;

* start/end dates if applicable;

* metrics;

* source document;

* source section;

* source text;

* verified status;

* optional embedding;

* created/updated timestamps.



Example:



{

"claim_id": 441,

"category": "experience",

"employer": "Example Company",

"skills": ["Power BI", "SQL"],

"claim": "Built Power BI dashboards using SQL-backed data.",

"verified": true

}



⸻



CandidateAnswers



Canonical application answers.



Examples:



work_authorization

sponsorship_required

relocation

start_date

salary_minimum

salary_target

travel_percentage

security_clearance



Support:



* typed values;

* optional explanatory text;

* provenance;

* user-confirmed flag.



⸻



VoluntaryDisclosures



Separate table.



Store only responses explicitly supplied by the candidate.



⸻



SearchProfiles



Store:



* profile name;

* titles;

* locations;

* remote/hybrid/on-site;

* salary minimum;

* desired levels;

* excluded titles;

* excluded employers;

* keywords;

* enabled status.



⸻



Jobs



Store:



* internal ID;

* canonical job key;

* ATS;

* external job ID;

* company;

* normalized company;

* title;

* normalized title;

* location;

* remote type;

* salary;

* description;

* description hash;

* canonical application URL;

* first seen;

* last seen;

* job status.



⸻



JobSources



Allow multiple source records for one Job.



Store:



* job ID;

* provider;

* source URL;

* discovered timestamp;

* external source ID.



⸻



JobRequirements



Store each extracted requirement separately.



Fields:



* job ID;

* requirement type;

* normalized requirement;

* required/preferred;

* source quote/text;

* confidence;

* weight.



⸻



JobEvaluations



Store:



* deterministic hard-filter result;

* required qualification coverage;

* preferred qualification score;

* domain alignment;

* seniority alignment;

* preference alignment;

* overall qualification score;

* disqualifiers;

* gaps;

* model used if applicable;

* evaluation version.



⸻



GeneratedDocuments



Store:



* application/job ID;

* type;

* local path;

* format;

* generated timestamp;

* template version;

* source claim IDs;

* content hash.



⸻



CandidateAccounts



Store:



* employer;

* ATS;

* tenant/site identifier;

* career-site origin;

* username/email;

* credential reference;

* account status;

* date created;

* last successful login.



Passwords are never stored in this table.



⸻



Applications



Store one row per actual application attempt.



Fields:



* application ID;

* job ID;

* current state;

* submission mode;

* adapter;

* adapter version;

* queued time;

* claim/lease information;

* started time;

* submitted time;

* verified time;

* retry count;

* last error;

* resume document ID;

* confirmation ID/text;

* final URL.



⸻



ApplicationEvents



Append-only event history.



Fields:



* application ID;

* event type;

* timestamp;

* sanitized metadata;

* adapter/page state.



⸻



ApplicationAnswers



Store:



* application ID;

* question;

* normalized question;

* answer category;

* answer submitted;

* source;

* claim IDs used;

* confidence;

* whether user approved.



Sensitive disclosure answers should be protected separately.



⸻



QuestionMappings



Store known question → canonical answer mappings.



Example:



"Will you now or in the future require sponsorship?"

→ sponsorship_required



⸻



FieldMappings



Store successful mappings by ATS.



Fields:



* ATS;

* normalized label;

* DOM signature;

* canonical candidate field;

* confidence;

* success count;

* last validated date.



⸻



ModelRuns



Store:



* purpose;

* model;

* prompt version;

* timestamp;

* token usage;

* estimated cost;

* success/failure;

* output validation status.



Do not store secrets or unnecessary sensitive prompt contents.



⸻



10. Resume Ingestion



Endpoint:



POST /api/v1/profile/resume/parse



Accept:



* PDF;

* DOCX.



Maximum file size must be configured.



Processing pipeline



Upload

↓

Validate file

↓

Extract text locally

↓

Assess extraction quality

↓

OCR fallback only if necessary

↓

Structured LLM extraction

↓

Pydantic validation

↓

Candidate review

↓

Commit profile



Use PyMuPDF for ordinary PDFs and python-docx for DOCX.



Do not send a complete binary resume to an external LLM when locally extracted text is sufficient.



If a document is scanned and requires OCR, attempt local OCR first or use an approved vision-capable fallback with explicit product configuration.



⸻



11. Structured Candidate Extraction



The LLM must return a predefined JSON schema.



At minimum:



{

"contact": {},

"employment": [],

"education": [],

"skills": [],

"certifications": [],

"projects": []

}



Use:



* provider-supported JSON schema/structured output;

* Pydantic validation;

* no more than two structured retries;

* fallback model after repeated schema failure.



Do not treat Pydantic alone as model-output enforcement.



⸻



12. Verified Claim Generation



Do not merely split resume bullets into sentences.



Convert resume content into atomic factual claims.



Example input:



Built Power BI dashboards using SQL that reduced monthly reporting time by 30%.



Potential structured evidence:



Claim 1: Built Power BI dashboards.

Claim 2: Used SQL in dashboard/reporting work.

Claim 3: Reduced monthly reporting time by 30%.



Retain the original source text for all three.



The candidate must have an opportunity during onboarding to review or correct important extracted claims.



⸻



13. Application Answer Library



During onboarding, collect common deterministic answers once.



Include:



* work authorization;

* sponsorship;

* relocation;

* start date;

* salary minimum;

* salary target;

* travel;

* security clearance;

* willingness to undergo background screening where appropriate;

* remote/hybrid preferences.



For experience-duration questions, do not let an LLM guess.



Create a deterministic experience calculator:



1. associate verified claims with date ranges;

2. combine overlapping date intervals for the same skill;

3. avoid double-counting simultaneous jobs/projects;

4. calculate total supported duration;

5. if dates are insufficient, use a user-approved override or request input.



⸻



14. User Dashboard



Build the dashboard as the primary customer interface.



FastAPI should serve the production-built React assets locally.



Example:



http://127.0.0.1:8765/app



The Chrome extension toolbar popup should contain only:



* Start/Pause;

* status;

* Needs Attention count;

* Open Dashboard.



⸻



15. Onboarding Wizard



The first-run wizard should be no longer than necessary.



Step 1



Upload resume.



Step 2



Review:



* name;

* contact information;

* jobs;

* education;

* skills.



Step 3



Answer application questions.



Step 4



Configure job targets.



Step 5



Configure automation.



Allow:



Review before submission

Automatic submission on certified ATS adapters



Explain that CAPTCHA, MFA, new legal attestations, or unknown information may still require attention.



⸻



16. Job Discovery Architecture



Use a provider interface.



class DiscoveryProvider:

search(...)

normalize(...)

health_check(...)



Initial providers should include, where current access and terms permit:



* Greenhouse employer job feeds/pages;

* Lever public postings;

* employer career sites;

* optional Ashby provider;

* optional JobSpy provider for approved sources;

* future licensed job-data provider.



Do not make JobSpy an architectural dependency.



JobSpy itself documents source-specific limitations and notes LinkedIn as particularly restrictive. Treat it as a replaceable discovery adapter, not the core system. (GitHub⁠￼)



⸻



17. Discovery Compliance Registry



Each source must carry configuration:



source

enabled

permitted_for_discovery

permitted_for_application

requires_auth

rate_policy

notes



Production defaults must disable direct automated application execution on LinkedIn and Indeed Apply.



Do not attempt to overcome blocked scraping through proxies or other evasion mechanisms.



If broad commercial job coverage later requires a licensed data provider, add it behind the same DiscoveryProvider interface.



⸻



18. Discovery Scheduling



Use APScheduler in the Python backend.



Default:



2 discovery runs/day



User may change schedule.



Discovery should continue independently of Chrome availability.



⸻



19. Job Normalization



Normalize:



* company name;

* title;

* location;

* remote type;

* salary;

* ATS;

* source;

* canonical application URL.



Strip tracking URL parameters when safe.



Save description text and a description hash.



⸻



20. Deduplication



Preferred key order:



1. ATS + external job ID

2. normalized canonical application URL

3. SHA-256(

normalized company

+ normalized title

+ normalized location

)



Do not use Python’s runtime hash() for persistent IDs.



A job found through multiple sources becomes:



1 Jobs record

N JobSources records



⸻



21. Qualification Pipeline



Use four stages.



Stage 1 — Hard constraints



Cost: $0.



Evaluate:



* location;

* workplace type;

* employment type;

* salary when provided;

* work authorization;

* sponsorship;

* explicit clearance;

* excluded employer;

* excluded title;

* seniority.



Missing data is not automatically a failure.



Represent constraint state as:



PASS

FAIL

UNKNOWN



⸻



Stage 2 — Structured requirement extraction



Send remaining job descriptions to the inexpensive structured-output model.



Extract:



{

"normalized_title": "",

"seniority": "",

"required_years": null,

"employment_type": "",

"remote_policy": "",

"salary": {},

"work_authorization": {},

"sponsorship": {},

"clearance": null,

"education_required": [],

"certifications_required": [],

"required_skills": [],

"preferred_skills": [],

"required_domain_experience": [],

"travel_requirement": null

}



Every requirement must include:



* required vs preferred;

* confidence;

* supporting source text.



⸻



22. Candidate Evidence Matching



For each job requirement:



Requirement

↓

Retrieve candidate evidence

↓

Evaluate evidence

↓

MET

PARTIALLY_MET

NOT_MET

UNKNOWN



Embeddings may assist evidence retrieval.



Embeddings do not decide whether the applicant is qualified.



For the small number of candidate claims expected per user, a full external vector database is unnecessary.



Store embeddings in SQLite or calculate them in a lightweight local matrix.



⸻



23. Qualification Score



Use an interpretable weighted score.



Recommended initial framework:



Required qualifications 55%

Preferred qualifications 15%

Domain experience 10%

Seniority alignment 10%

Candidate preferences 10%



Store component scores separately.



Auto-application requires:



1. no explicit hard disqualifier;

2. required-qualification coverage above configured threshold;

3. overall score above configured threshold;

4. no unresolved critical requirement;

5. confidence above configured threshold.



These thresholds are product configuration values—not universal truths.



The UI must show why a job qualified.



⸻



24. Optional AI Sanity Check



For only high-scoring jobs, optionally call the cheap LLM with:



* structured job requirements;

* matched verified claims;

* identified gaps.



Return:



{

"material_gap": false,

"risk": "low",

"evidence_strength": "high",

"notes": []

}



This is a final quality check, not the primary scoring mechanism.



⸻



25. Automated Resume Tailoring



Every auto-applied job should have the option to receive a tailored resume.



Pipeline:



Job requirements

+

Master resume

+

VerifiedClaims

↓

Content selection

↓

Controlled rewriting

↓

Claim validation

↓

Document rendering

↓

GeneratedDocuments



The model may:



* reorder bullets;

* select relevant accomplishments;

* rephrase supported claims;

* emphasize relevant skills;

* adjust summary;

* remove irrelevant content.



The model may not add unsupported facts.



⸻



26. Resume Generation Contract



The model should return structured content rather than arbitrary formatted text.



Example:



{

"summary": "...",

"experience": [

{

"employment_id": 12,

"bullets": [

{

"text": "...",

"source_claim_ids": [41, 42]

}

]

}

],

"skills": [...]

}



Validate:



* every referenced claim exists;

* dates have not changed;

* employer names have not changed;

* certifications have not appeared from nowhere;

* new numeric metrics are not introduced;

* unsupported technologies are not introduced.



If validation fails, retry once or use original candidate wording.



⸻



27. Resume Rendering



Render deterministically.



Produce:



* ATS-friendly PDF;

* optional DOCX.



Use a standardized single-column template.



Avoid:



* text boxes;

* graphics used for essential information;

* columns that confuse parsers;

* embedded images;

* icons instead of text.



Use HTML/template → PDF and a deterministic DOCX generator.



Store local generated file path and content hash.



⸻



28. Application Queue



Once a job qualifies and its resume is ready:



APPROVED

↓

DOCUMENT_READY

↓

QUEUED



Do not mark the Job itself as “OPENED” or “SUBMITTED.”



Application execution state belongs in the Applications table.



⸻



29. Atomic Application Claiming



Endpoint:



POST /api/v1/applications/claim-next



It must perform an atomic database transaction.



Return:



{

"application_id": 991,

"lease_id": "uuid",

"lease_expires_at": "...",

"job_url": "...",

"ats": "workday"

}



If the browser disappears or application execution stops, the lease must eventually expire.



Expired claims return to the queue subject to retry policy.



This prevents permanent stranded jobs.



⸻



30. Application State Machine



Use states such as:



QUEUED

CLAIMED

OPENING

ATS_DETECTED

ACCOUNT_CHECK

AUTHENTICATING

FILLING

VALIDATING

AWAITING_EXTERNAL_ACTION

READY_TO_SUBMIT

SUBMITTING

SUBMITTED

VERIFIED

SUBMISSION_UNVERIFIED

FAILED_RETRYABLE

FAILED_PERMANENT



Every transition must create an ApplicationEvent.



⸻



31. Standard Error Codes



At minimum:



CAPTCHA_REQUIRED

LOGIN_REQUIRED

ACCOUNT_CREATION_REQUIRED

EMAIL_VERIFICATION_REQUIRED

MFA_REQUIRED

PASSWORD_RESET_REQUIRED

ACCOUNT_LOCKED

AUTH_FAILED

FIELD_MAPPING_FAILED

QUESTION_UNSUPPORTED

MISSING_CANDIDATE_DATA

UPLOAD_FAILED

VALIDATION_FAILED

JOB_CLOSED

ALREADY_APPLIED

EMPLOYER_APPLICATION_LIMIT

ATS_CHANGED

NETWORK_ERROR

BACKEND_UNAVAILABLE

MODEL_ERROR

SUBMISSION_UNVERIFIED



⸻



32. Chrome Manifest V3



The extension should request only needed permissions.



Likely:



alarms

storage

tabs

scripting

notifications



Host permissions:



* local FastAPI origin;

* supported ATS origins.



Do not request arbitrary *://*/* production permissions unless absolutely required and justified.



Set a tested minimum Chrome version that supports the required MV3 behaviors.



⸻



33. MV3 Service Worker



The service worker is event-driven.



Do not use setInterval() as the reliable orchestration mechanism.



Use:



chrome.alarms

chrome.tabs

chrome.runtime messaging



Workflow:



Alarm fires

↓

Check automation enabled

↓

Claim next application

↓

Create ATS tab

↓

Adapter/content script runs

↓

Content events wake worker

↓

Worker forwards events to FastAPI



At startup/install, confirm required alarms exist and recreate them when necessary.



Never rely on persistent global state.



⸻



34. Browser Concurrency



Default:



MAX_CONCURRENT_APPLICATIONS=1



Support 2 only after reliability testing.



Do not create many simultaneous ATS tabs.



The goal is reliability, not maximum browser throughput.



⸻



35. ATS Adapter Interface



Implement a standard interface comparable to:



interface ATSAdapter {

detect(): boolean;

initialize(): Promise<void>;

detectPage(): PageState;

discoverFields(): Promise<Field[]>;

mapFields(): Promise<FieldMapping[]>;

uploadResume(): Promise<void>;

processQuestions(): Promise<void>;

validatePage(): Promise<ValidationResult>;

nextPage(): Promise<void>;

canSubmit(): Promise<boolean>;

submit(): Promise<void>;

verifySubmission(): Promise<SubmissionResult>;

}



Shared functions belong in the form engine, not duplicated between adapters.



⸻



36. Adapter Priority



Recommended build order:



1. Greenhouse;

2. Lever;

3. Ashby;

4. generic ATS fallback;

5. Workday;

6. SmartRecruiters;

7. iCIMS;

8. additional ATSs based on observed volume.



Workday should not delay proving the core architecture.



⸻



37. ATS Detection



Use multiple signals:



* hostname;

* URL path;

* DOM markers;

* form structure;

* page metadata.



Never trust one CSS selector as the complete detection mechanism.



⸻



38. Form Discovery Engine



Inspect:



tag

type

id

name

label

aria-label

placeholder

autocomplete

role

required

options

nearby text

DOM hierarchy



Support:



* text;

* email;

* telephone;

* textarea;

* select;

* checkbox;

* radio;

* date;

* numeric;

* multi-select;

* custom combobox;

* autocomplete;

* file input.



⸻



39. Controlled Input Handling



Modern React/Angular sites may not detect a simple assignment to element.value.



The form engine must:



1. use the appropriate native property setter where required;

2. dispatch expected input;

3. dispatch change;

4. dispatch blur when needed;

5. confirm the displayed value persisted.



Never assume that setting a DOM property means the application accepted the value.



⸻



40. Dynamic Pages



Use:



* MutationObserver;

* explicit page-state detection;

* DOM-ready conditions;

* element readiness checks.



Do not rely primarily on arbitrary 15–45 second sleeps.



Short bounded waits are acceptable for rendering, but waits should be driven by observable state whenever possible.



⸻



41. Iframes and Shadow DOM



Adapters must detect whether fields are:



* top-level DOM;

* same-origin iframe;

* permitted cross-origin iframe;

* open shadow root.



Where extension permissions permit, inject into relevant frames.



Closed shadow roots or inaccessible embedded components should trigger a controlled fallback rather than uncontrolled clicking.



⸻



42. Resume Upload



Endpoint:



GET /api/v1/applications/{id}/resume



The service worker obtains the generated resume as binary data and forwards it to the trusted adapter path.



Where technically supported:



1. construct a File;

2. use a DataTransfer;

3. populate the file input;

4. dispatch the appropriate event;

5. confirm filename/upload completion.



Some ATS interfaces may require a different strategy; handle that in the adapter.



After resume upload:



wait for ATS parsing

↓

re-scan fields

↓

correct parsed values



Resume parsing can overwrite previously entered fields.



⸻



43. Candidate Account Management



Authentication is a first-class subsystem.



For every ATS career site:



Detect authentication requirement

↓

Determine employer/tenant

↓

Known account?

├── yes → authenticate

└── no → create/recover



⸻



44. ATS Tenant Identity



Do not treat “Workday” as one global account.



Derive a stable tenant key from:



* ATS;

* normalized employer;

* career-site origin;

* employer/site identifier.



One candidate may have many Workday accounts.



⸻



45. Credential Storage



Use Python keyring to interact with:



* Windows Credential Manager;

* macOS Keychain;

* Linux Secret Service/keyring.



SQLite stores:



credential_reference



not:



password



Passwords must never enter:



* logs;

* application events;

* frontend state;

* persistent Chrome storage.



⸻



46. Password Creation



Use Python secrets, not random.



Generate unique passwords per employer/tenant.



Workflow:



Generate strong password

↓

Attempt account creation

↓

Rejected by password policy?

↓

Read displayed requirements

↓

Generate compliant replacement

↓

Store only successful password



Do not reuse one password across employers.



⸻



47. Credential Delivery to Browser



Only the service worker should request a credential from FastAPI.



Backend must require:



* application ID;

* tenant identifier;

* exact permitted origin.



Return credential only if they match the stored candidate account.



The password should exist in extension memory only long enough to populate the verified login page.



Never expose it through the dashboard or content-script persistent storage.



⸻



48. Existing Account Detection



If the site says an email already exists and no credential is stored:



ACCOUNT_EXISTS_CREDENTIAL_UNKNOWN



Then:



* request user sign-in; or

* start password recovery.



After successful recovery, store the new credential securely.



⸻



49. Email Verification



Baseline product behavior:



EMAIL_VERIFICATION_REQUIRED

↓

Needs Attention

↓

Browser notification

↓

User verifies email

↓

Application resumes



Do not require inbox access for V1.



Optional later capability:



* Gmail/Outlook OAuth;

* verification-email identification;

* user-authorized link handling.



This must remain opt-in.



⸻



50. MFA



Never attempt to bypass MFA.



Set:



MFA_REQUIRED



Notify the user and leave the correct browser tab accessible.



Resume automatically after successful authentication.



⸻



51. Legal Attestations



Do not let an LLM decide whether to accept:



* applicant certifications;

* electronic signatures;

* legal releases;

* consent statements;

* criminal-history declarations;

* binding terms.



If the exact attestation has not been explicitly approved under the product’s user-policy framework:



AWAITING_EXTERNAL_ACTION



A user may configure reusable answers only for clearly defined factual declarations.



⸻



52. Workday Adapter



Do not assume a fixed number of pages.



Workday flows are tenant-configurable.



The adapter must identify the actual state dynamically.



Possible states include:



Sign In

Create Account

Resume/CV

Contact Information

Work Experience

Education

Application Questions

Voluntary Disclosures

Review

Submit

Candidate Home



Workday Candidate Home may be mandatory and may offer previous-application reuse. (Workday Documentation⁠￼)



If Workday offers:



Use My Last Application

Upload a New Resume or CV



prefer the new tailored resume when job-specific resume tailoring is enabled.



Then reconcile the fields after Workday parsing.



⸻



53. Greenhouse and Lever



Implement dedicated adapters.



Support:



* contact information;

* resume;

* custom questions;

* standard candidate questions;

* voluntary disclosure sections when present;

* submission confirmation.



Do not attempt direct applicant API POSTs unless the system legitimately possesses employer-side integration credentials. (Greenhouse Support⁠￼)



⸻



54. Question Resolution Engine



Use the following waterfall:



Question

↓

Known exact/canonical mapping?

├─ yes → stored answer

↓

Known question category?

├─ yes → deterministic answer/calculation

↓

Can candidate evidence answer it?

├─ yes → evidence-grounded generation

↓

Unknown factual/legal question

→ Needs Attention



⸻



55. Question Categories



At minimum classify:



identity

address

work_authorization

sponsorship

relocation

salary

availability

travel

years_experience

skill_experience

education

certification

security_clearance

work_history

EEO

legal_attestation

open_experience

motivation

company_interest



⸻



56. Questions That Must Not Be Guessed



Do not generatively invent answers for:



* citizenship;

* work authorization;

* sponsorship;

* security clearance;

* criminal history;

* certifications;

* licenses;

* salary expectations;

* years of experience;

* voluntary demographic information.



These require explicit user data or deterministic calculation.



⸻



57. Evidence-Grounded Q&A Endpoint



Endpoint:



POST /api/v1/applications/{id}/questions/resolve



Input:



{

"question": "...",

"field_type": "textarea",

"options": []

}



Output:



{

"resolution": "GENERATED",

"answer": "...",

"claim_ids": [12, 44],

"confidence": 0.95

}



Model prompt requirements:



* use only supplied evidence;

* concise answer;

* no unsupported claims;

* obey configured word/character limit;

* return claim IDs;

* return confidence.



⸻



58. Generated Answer Validation



After generation:



* referenced claims must exist;

* numbers must be traceable;

* dates must be traceable;

* named technologies must be supported;

* length must satisfy the form;

* answer cannot contradict canonical profile data.



If validation fails:



1. retry once with stricter evidence;

2. otherwise request human input.



⸻



59. Learning From Questions



When a previously unknown deterministic question is successfully resolved, save a normalized mapping.



Example:



"Do you currently or in the future need employment sponsorship?"

category:

sponsorship_required



Future applications should avoid an LLM call for equivalent questions.



⸻



60. Voluntary Disclosures



Only use user-provided preferences.



Support:



* explicit answer;

* prefer not to answer;

* ask each time.



Never infer demographic data from:



* name;

* photograph;

* employment;

* geography;

* school;

* language.



⸻



61. Pre-Submission Validator



No adapter may submit until validation passes.



Check:



Job still open?

Correct employer?

Correct candidate?

Correct tailored resume?

All required fields populated?

No visible validation errors?

Every required question resolved?

No unsupported factual claim?

No pending legal attestation?

No CAPTCHA/MFA?

No duplicate application?

No employer limit detected?



Then set:



READY_TO_SUBMIT



⸻



62. Duplicate Application Protection



Before opening the ATS and again immediately before submission, query application history.



Check:



* same external job ID;

* same canonical job URL;

* same employer/title/location fallback;

* prior application status.



Do not submit again unless explicitly permitted by configured policy.



⸻



63. Submission



Use adapter-specific submission logic.



State sequence:



READY_TO_SUBMIT

↓

SUBMITTING

↓

SUBMITTED



Do not mark the application VERIFIED yet.



⸻



64. Submission Verification



Verify using one or more:



* success page;

* confirmation text;

* confirmation URL;

* application ID;

* Candidate Home status.



If success is established:



VERIFIED



If the click occurred but success cannot be established:



SUBMISSION_UNVERIFIED



Never silently treat uncertainty as success.



⸻



65. Application Rate Controller



Create a dedicated ApplicationRateController.



Default product settings:



Daily target: 25

Daily hard ceiling: 40

Weekly hard ceiling: 200

Same employer / 7 days: 3

Concurrent applications: 1



These are product-quality defaults, not claims of universal ATS-safe limits.



All must be configurable.



⸻



66. Adaptive Throttling



Monitor:



* CAPTCHA rate;

* email-verification rate;

* MFA frequency;

* account failures;

* HTTP 429;

* employer limit warnings;

* ATS validation failures;

* submission-unverified rate;

* adapter error rate.



If abnormal activity increases:



reduce/pause affected provider



Do not attempt to evade the control.



Respect Retry-After when provided.



⸻



67. Provider-Specific Pausing



A problem with one source or ATS must not halt the whole platform.



Example:



Greenhouse healthy

Lever healthy

Workday elevated errors → PAUSED



Continue supported sources.



⸻



68. Retry Policy



Classify failures.



Automatically retry



* temporary network failure;

* local backend restart;

* temporary ATS 5xx;

* tab crash;

* model-provider timeout.



Delayed retry



* rate-limit response;

* temporary ATS maintenance.



User action



* CAPTCHA;

* MFA;

* email verification;

* unknown credential;

* unknown legal attestation;

* missing factual information.



Permanent stop



* job closed;

* duplicate application;

* clear candidate disqualification;

* account permanently blocked;

* employer application restriction.



Use capped exponential backoff.



Never retry forever.



⸻



69. Application Tracking Dashboard



The Applications screen is backed directly by SQLite.



Required statuses include:



Queued

In Progress

Applied

Verified

Needs Attention

Submission Unverified

Failed

Interview

Rejected

Offer

Withdrawn



Statuses after submission such as Interview, Rejected, or Offer can initially be updated manually.



Email integration may automate these later.



⸻



70. Application Detail Screen



Clicking one row must display:



* company;

* position;

* job posting;

* date;

* ATS;

* match breakdown;

* resume used;

* application questions and submitted answers;

* confirmation information;

* application event timeline;

* current status.



Do not display stored passwords.



⸻



71. Excel and CSV Export



SQLite remains the source of truth.



Provide:



GET /api/v1/exports/applications.xlsx

GET /api/v1/exports/applications.csv



Dashboard buttons:



Export to Excel

Export to CSV



Optional setting:



Automatically create a daily Excel snapshot



⸻



72. Excel Workbook Structure



Generate at least two sheets.



Applications



Columns:



Application ID

Date Discovered

Date Applied

Company

Job Title

Location

Work Arrangement

Salary

Source

ATS

Qualification Score

Required Qualification Coverage

Application Status

Resume Used

Job URL

Confirmation

Notes



URLs should be clickable hyperlinks.



⸻



Summary



Include:



Total applications

Applications today

Applications this week

Applications this month

Needs attention

Verified submissions

Interviews

Offers



Also summarize:



* applications by status;

* applications by ATS;

* applications by company;

* applications by week.



Do not make Excel the authoritative database.



⸻



73. Logging



Use structured application logs.



Track:



* discovery run;

* source failures;

* jobs discovered;

* deduplication;

* qualification decisions;

* application state;

* adapter/page state;

* retries;

* model invocation;

* submission verification.



Never log:



* passwords;

* API keys;

* authentication tokens;

* complete EEO responses;

* unnecessary personal data.



⸻



74. Health and Statistics APIs



Implement:



GET /api/v1/health

GET /api/v1/version

GET /api/v1/stats



/version should include:



* backend version;

* API protocol version;

* database schema version.



The extension must verify protocol compatibility.



⸻



75. Core API Surface



At minimum implement:



POST /api/v1/profile/resume/parse

GET /api/v1/profile

PATCH /api/v1/profile

GET /api/v1/search-profiles

POST /api/v1/search-profiles

PATCH /api/v1/search-profiles/{id}

POST /api/v1/discovery/run

GET /api/v1/jobs

GET /api/v1/jobs/{id}

GET /api/v1/applications

GET /api/v1/applications/{id}

POST /api/v1/applications/claim-next

POST /api/v1/applications/{id}/heartbeat

POST /api/v1/applications/{id}/events

POST /api/v1/applications/{id}/transition

GET /api/v1/applications/{id}/resume

POST /api/v1/applications/{id}/questions/resolve

GET /api/v1/actions

POST /api/v1/actions/{id}/resolve

GET /api/v1/accounts

POST /api/v1/automation/start

POST /api/v1/automation/pause

GET /api/v1/automation/status

GET /api/v1/exports/applications.xlsx

GET /api/v1/exports/applications.csv

GET /api/v1/health

GET /api/v1/version

GET /api/v1/stats



Credential retrieval should use a restricted extension-only endpoint and should never be exposed to the dashboard.



⸻



76. Model Routing



Create a provider-neutral ModelRouter.



Support:



FAST

FALLBACK

ESCALATION

EMBEDDING



Example policy:



Structured extraction

→ FAST

Invalid structured output twice

→ FALLBACK

Highly ambiguous non-factual question

→ FALLBACK or ESCALATION

Browser navigation

→ no LLM



The system must remain functional if the primary model becomes unavailable.



⸻



77. Cost Controls



Track token usage and estimated cost in ModelRuns.



Use:



* structured short outputs;

* cached candidate evidence;

* deterministic question mappings;

* deterministic qualification calculations;

* retrieval of only relevant claims.



Do not repeatedly send the entire resume to the LLM for every application.



Target normal variable AI cost:



≤ approximately $5 per active user/month



under ordinary usage, excluding optional paid job-data providers.



This is a product target, not a guaranteed fixed cost.



⸻



78. Browser Notifications



Use Chrome notifications for:



* CAPTCHA;

* MFA;

* verification;

* unknown account;

* required user answer;

* automation paused;

* severe adapter failure.



Do not notify for every successful application.



The dashboard remains the primary status surface.



⸻



79. Automation Modes



Support:



PAUSED

REVIEW

AUTO



REVIEW



Complete application but stop before Submit.



AUTO



Submit automatically only through adapters certified for auto-submission.



Unknown or unsupported cases still route to Needs Attention.



⸻



80. Adapter Certification Levels



Each adapter should have:



DISABLED

REVIEW_ONLY

AUTO_SUBMIT



Do not make every new adapter auto-submit immediately.



Promotion to AUTO_SUBMIT requires acceptance testing.



⸻



81. Testing Strategy



Backend unit tests



Cover:



* normalization;

* deduplication;

* state transitions;

* leases;

* retries;

* requirement scoring;

* experience duration;

* question classification;

* export generation;

* resume validation.



⸻



Database tests



Test:



* migrations;

* rollback/recovery;

* foreign-key integrity;

* transaction behavior;

* concurrent application claim attempts.



⸻



Model contract tests



Mock model responses.



Test:



* valid JSON;

* invalid JSON;

* missing required fields;

* hallucinated resume content;

* unsupported metrics;

* schema retries;

* fallback model behavior.



⸻



82. ATS Fixture Tests



Maintain sanitized HTML fixtures for every supported adapter.



Fixtures should cover:



* ordinary application;

* required fields;

* custom questions;

* resume upload;

* validation errors;

* multi-page flows;

* account creation;

* login;

* submission confirmation.



When an ATS changes:



capture sanitized fixture

↓

reproduce failure

↓

fix adapter

↓

add regression test



⸻



83. Browser Integration Tests



Use Playwright or equivalent for testing only.



Test a local mock ATS application capable of simulating:



* Greenhouse-like page;

* Lever-like page;

* Workday multi-page workflow;

* account creation;

* file upload;

* CAPTCHA placeholder;

* MFA placeholder;

* success/failure confirmation.



⸻



84. Workday Testing



Test at minimum:



new account

existing account

unknown password

email verification

use previous application

upload new resume

multi-page application

custom questions

optional EEO

required EEO

review page

successful submission



Do not promote Workday to AUTO until reliability is demonstrated.



⸻



85. Auto-Submission Quality Gate



Before an adapter becomes AUTO_SUBMIT, it must demonstrate in controlled testing:



* ≥98% correct required-field population;

* 100% detection of unresolved required fields in the test suite;

* no unsupported candidate claims;

* no automatically accepted unknown legal attestations;

* reliable resume upload;

* reliable duplicate prevention;

* reliable submission verification;

* no known critical data-mapping defect.



Any critical false-submission defect returns the adapter to REVIEW_ONLY.



⸻



86. CI Quality Gates



Backend:



ruff

mypy

pytest



Frontend/extension:



eslint

TypeScript type check

unit tests

browser integration tests



No release should ship if migrations or adapter regression tests fail.



⸻



87. Packaging



The end user should not manually run Python.



Package the backend as a local desktop/service application.



Suggested:



* PyInstaller or equivalent Python packaging;

* signed installer where applicable;

* bundled dashboard assets;

* database migration at startup.



⸻



88. Startup Behavior



At user login:



Local agent starts

↓

Single-instance lock acquired

↓

Database opened

↓

Migrations applied

↓

Scheduler starts

↓

127.0.0.1 API starts

↓

Extension health check succeeds



The backend must prevent multiple competing instances.



⸻



89. Extension Installation



Development:



Load unpacked



Production:



Chrome Web Store or managed distribution



The extension and backend must use semantic versioning.



⸻



90. Version Compatibility



Backend:



{

"backend_version": "1.0.0",

"api_version": "1",

"schema_version": "12"

}



Extension checks compatibility before starting applications.



If incompatible:



Automation Paused

Update Required



Never continue on an untested protocol mismatch.



⸻



91. Data Deletion



Provide:



Delete Application History

Delete Candidate Profile

Delete Generated Documents

Delete Stored ATS Accounts

Delete All Local Data



Deleting stored ATS accounts must also remove credential-store secrets.



⸻



92. Privacy Controls



Provide clear settings for:



* AI provider usage;

* voluntary disclosure responses;

* data retention;

* application-answer history.



Do not send passwords, demographic responses, or authentication tokens to an LLM.



⸻



93. Operational Metrics



Track:



jobs discovered

jobs deduplicated

jobs rejected by hard filter

qualified jobs

applications queued

applications verified

applications needing attention

submission-unverified rate

adapter failure rate

CAPTCHA rate

auth intervention rate

model cost



Use these metrics to identify adapters that should be automatically demoted from AUTO to REVIEW mode.



⸻



94. Build Sequence



Build in this order.



Milestone 1 — Foundation



Deliver:



* repository;

* backend;

* SQLite;

* Alembic;

* configuration;

* local authentication;

* React shell;

* extension shell.



Acceptance:



Dashboard ↔ FastAPI ↔ Extension communication works.



⸻



Milestone 2 — Candidate Onboarding



Deliver:



* resume upload;

* text extraction;

* structured parsing;

* profile review;

* VerifiedClaims;

* CandidateAnswers.



Acceptance:



New user can build a complete candidate profile from PDF/DOCX.



⸻



Milestone 3 — Discovery



Deliver:



* provider interface;

* Greenhouse/Lever discovery;

* normalization;

* deduplication;

* search profiles;

* scheduled discovery.



Acceptance:



Jobs enter SQLite without duplicates.



⸻



Milestone 4 — Qualification



Deliver:



* hard filters;

* structured extraction;

* evidence matching;

* qualification scoring;

* explanation UI.



Acceptance:



Qualified jobs contain an auditable score and supporting candidate evidence.



⸻



Milestone 5 — Resume Tailoring



Deliver:



* job-specific claim selection;

* controlled rewriting;

* validation;

* PDF/DOCX renderer.



Acceptance:



Every generated resume traces factual content to candidate evidence.



⸻



Milestone 6 — Extension Execution



Deliver:



* application lease;

* tab management;

* event messaging;

* form engine;

* resume upload;

* generic adapter.



Acceptance:



Mock ATS form can be completed end-to-end.



⸻



Milestone 7 — Greenhouse and Lever



Deliver:



* adapters;

* Q&A;

* validation;

* submission;

* verification.



Initially run REVIEW mode.



After certification, promote to AUTO.



⸻



Milestone 8 — Account Management



Deliver:



* CandidateAccounts;

* OS credential storage;

* account creation;

* login;

* recovery state;

* verification handling;

* Accounts UI.



Acceptance:



Credentials persist securely and can be reused without storing plaintext in SQLite or Chrome.



⸻



Milestone 9 — Workday



Deliver:



* tenant detection;

* Candidate Home;

* account creation;

* login;

* previous application detection;

* new resume upload;

* multi-page navigation;

* questions;

* review;

* submission.



Start REVIEW_ONLY.



Promote only after certification.



⸻



Milestone 10 — Dashboard and Export



Deliver polished:



* Home;

* Applications;

* Application Details;

* Needs Attention;

* Accounts;

* Profile;

* Preferences;

* Excel;

* CSV.



⸻



Milestone 11 — Rate Governance and Recovery



Deliver:



* daily/weekly limits;

* employer limits;

* adaptive pausing;

* leases;

* retry engine;

* provider health;

* crash recovery.



⸻



Milestone 12 — Production Packaging



Deliver:



* installer;

* startup registration;

* extension distribution;

* version compatibility;

* upgrade path;

* automated migrations;

* regression suite.



⸻



95. Required End-to-End Acceptance Test



The product is not complete until this scenario passes:



User setup



1. Fresh installation.

2. Extension pairs to local backend.

3. User uploads resume.

4. Resume is correctly parsed.

5. User corrects one profile field.

6. User answers standard application questions.

7. User creates a job-search profile.

8. User enables automation.



Discovery



9. Discovery finds jobs.

10. Duplicates are merged.

11. Poor-fit jobs are filtered.

12. Requirements are extracted.

13. Candidate evidence is matched.

14. Qualified job is approved.



Resume



15. Job-specific resume is generated.

16. Every factual statement is validated.



Application



17. Application is queued.

18. Extension claims lease.

19. Employer ATS opens.

20. Correct adapter is detected.

21. Account requirement is detected.

22. Account is created or authenticated.

23. Resume is uploaded.

24. ATS parsing completes.

25. Fields are corrected.

26. deterministic questions are answered.

27. novel question is answered from VerifiedClaims.

28. required-field validation passes.

29. duplicate check passes.

30. submission occurs.

31. confirmation is detected.

32. application state becomes VERIFIED.



Tracking



33. Dashboard immediately shows the application.

34. Application Details shows resume and answers.

35. Excel export contains the application.

36. Application persists after browser/backend restart.



⸻



96. Required Failure Acceptance Tests



Also demonstrate:



Backend crashes mid-application

Chrome restarts

Tab closes unexpectedly

Model provider times out

ATS returns temporary failure

CAPTCHA appears

MFA appears

Email verification required

Unknown legal attestation appears

Existing Workday account password unknown

Resume upload fails

Required field cannot be mapped

Job closes before submission

Duplicate application detected

Submission result cannot be verified

Employer application limit detected



Every case must transition predictably without corrupting state or submitting unsupported information.



⸻



97. Definition of Done



The platform is production-ready only when all of the following are true:



* user can install without manually configuring Python;

* resume onboarding works;

* profile is editable;

* job searches are configurable;

* discovery is scheduled;

* jobs are deduplicated;

* qualifications are explainable;

* resume tailoring is evidence-constrained;

* candidate accounts are securely managed;

* passwords are stored only in OS credential storage;

* supported ATS adapters pass certification;

* unsupported cases fail safely;

* no CAPTCHA/access-control circumvention is implemented;

* unknown legal attestations require user action;

* direct automation is not performed on prohibited application surfaces;

* applications recover after restart;

* verified submissions appear in the dashboard;

* Excel and CSV exports work;

* automation can be paused instantly;

* daily, weekly, and employer limits work;

* application history is auditable;

* sensitive disclosures are isolated;

* all required regression tests pass.



⸻



98. Final Product Behavior



When complete, the normal user experience should be:



Install

↓

Upload Resume

↓

Review Profile

↓

Answer Setup Questions

↓

Choose Desired Jobs

↓

Enable Automation

↓

Jobs Discovered Automatically

↓

Jobs Qualified Automatically

↓

Resume Tailored Automatically

↓

ATS Account Created/Accessed Automatically

↓

Application Completed Automatically

↓

Application Validated Automatically

↓

Application Submitted Automatically

↓

Submission Verified

↓

Dashboard Updated

↓

Excel Tracking Updated



Human involvement should primarily occur for:



CAPTCHA

MFA

Email Verification

Unknown Credentials

Unknown Candidate Facts

New Legal Attestations

Unsupported ATS Behavior



Everything else should be designed for unattended execution.



The engineering priority order is:



accuracy → truthful applications → recovery → reliability → user simplicity → cost → raw submission volume.



The finished product should normally target approximately 25 applications per day, allow a configurable ceiling around 40 per day / 200 per week, and remain technically capable of greater throughput without making extreme volume the default product behavior.



The platform should never optimize throughput by weakening candidate-truth validation, pre-submission checks, rate governance, or external-platform controls.



This is the version I would use as the master build specification. The remaining work after handing it to the architect should be implementation and live adapter validation—not further architectural design. 

