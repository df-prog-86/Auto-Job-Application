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
