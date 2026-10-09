"""
Central, environment-driven configuration.

Nothing that materially changes product behavior is hard-coded — see spec §7.
All values here have safe, conservative defaults so a fresh checkout runs
without any .env file, but every one of them is meant to be overridden by the
user (via the Preferences UI, which writes to backend/data/.env or an
equivalent settings store — wired up in a later milestone).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Runtime ---------------------------------------------------------
    APP_ENV: str = "development"
    LOCAL_API_HOST: str = "127.0.0.1"  # never 0.0.0.0 outside controlled dev, see spec §8.2
    LOCAL_API_PORT: int = 8765

    # --- Storage ----------------------------------------------------------
    DATABASE_PATH: str = str(DEFAULT_DATA_DIR / "job_agent.db")
    GENERATED_DOCUMENTS_DIR: str = str(DEFAULT_DATA_DIR / "generated_documents")

    # --- Model routing (spec §76) -----------------------------------------
    # Provider-neutral: these are just identifiers the ModelRouter passes to
    # whichever OpenAI-compatible client is configured. No provider is wired
    # in yet — see services/llm/.
    LLM_API_BASE_URL: str | None = None
    LLM_API_KEY_REF: str | None = None  # keyring reference, never the raw key
    PRIMARY_FAST_MODEL: str | None = None
    FALLBACK_FAST_MODEL: str | None = None
    ESCALATION_MODEL: str | None = None
    EMBEDDING_MODEL: str | None = None

    # Job Search. The web lookup is billed per search by its engine (about $0.007 each on Exa, $0.001 on Parallel "fast"),
    # separately from the model. A separate model can be set for search; empty uses PRIMARY_FAST_MODEL.
    JOB_SEARCH_MODEL: str | None = None
    # Exa is the engine tried and known to honor the site filters. Parallel "fast" was tried and returned nothing (500 errors, empty results).
    JOB_SEARCH_ENGINE: str = "exa"  # "exa", "parallel", "perplexity" or "firecrawl"
    JOB_SEARCH_ENGINE_MODE: str | None = None  # exa: auto/fast/instant ($7 per 1,000), deep ($12); parallel: turbo/fast ($1), basic ($5)

    # Job cache: a local copy of employers' public job lists, searched instead of (and alongside) the web search.
    # It lives in its own database file so backups of job_agent.db stay small; it can always be rebuilt.
    JOB_CACHE_PATH: str = str(DEFAULT_DATA_DIR / "job_cache.db")
    JOB_CACHE_REFRESH_HOURS: int = 4  # how often the background refresh looks for employers that are due
    JOB_CACHE_MAX_POSTINGS: int = 300_000  # oldest closed postings go first when the copy grows past this
    # Hiring systems to switch off, comma separated: workday, greenhouse, lever, ashby. A kill switch if one ever objects.
    JOB_CACHE_DISABLED_SYSTEMS: str = ""
    JOB_CACHE_AUTO_REFRESH: bool = True  # False stops the app from reading employers on its own (tests turn it off)
    # "always": the AI web search runs with every search (it also finds new employers). "auto": it runs only when the
    # local copy found fewer results than asked for. "off": local copy only.
    JOB_SEARCH_AI: str = "always"

    # --- Discovery scheduling (spec §18) -----------------------------------
    DISCOVERY_INTERVAL_HOURS: int = 12

    # --- Application rate governance (spec §65) ----------------------------
    DAILY_APPLICATION_TARGET: int = 25
    DAILY_APPLICATION_LIMIT: int = 40
    WEEKLY_APPLICATION_LIMIT: int = 200
    EMPLOYER_WEEKLY_LIMIT: int = 3
    MAX_CONCURRENT_APPLICATIONS: int = 1

    # --- Qualification thresholds (spec §23) -------------------------------
    AUTO_APPLY_MIN_SCORE: float = 0.75
    AUTO_APPLY_MIN_REQUIRED_COVERAGE: float = 0.80
    AUTO_APPLY_MIN_CONFIDENCE: float = 0.70

    # --- Pairing / security (spec §8) --------------------------------------
    EXTENSION_ORIGIN_ALLOWLIST: list[str] = Field(default_factory=list)
    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024  # 10 MB, covers resume uploads

    # --- Resume ingestion (spec §10) ---------------------------------------
    MAX_RESUME_UPLOAD_BYTES: int = 15 * 1024 * 1024

    def ensure_dirs(self) -> None:
        Path(self.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.JOB_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.GENERATED_DOCUMENTS_DIR).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
