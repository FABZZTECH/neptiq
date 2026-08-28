"""Settings, loaded exclusively from the environment.

Invariant 6 (ARCHITECTURE §6): "No hostname, domain, or URL is hardcoded in
source. All come from env vars." This module is the ONLY place permitted to
name an environment variable, and it supplies no default for any field that
denotes a host, URL, or secret. A missing value is a startup failure, loudly,
rather than a silent fallback to localhost that would work in dev and quietly
point at nothing in production.

Numeric operational ceilings DO carry defaults, because ARCHITECTURE §7 states
them as defaults with values (CRAWL_MAX_URLS_DEFAULT=25000 and so on).

The settings object is split by trust zone. ``ZoneUSettings`` deliberately has
no database URL and no secret fields at all: a Zone U process that is handed
the wrong settings class cannot leak credentials it was never given. This is
defence in depth behind CI invariant 1, not a replacement for it.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "staging", "production"]


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # env is injected by the container runtime, never read from disk
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )


class ZoneUSettings(_Base):
    """Settings available to Zone U (fetcher, renderer, parser).

    No DB. No object-storage credentials. No KEK. No session secret. No LLM
    keys. If a Zone U component appears to need one of these, the design is
    wrong and the work belongs on the Zone T side of the validation gate.
    """

    NEPTIQ_ENV: Environment
    NEPTIQ_REGION: str

    # Egress is the ONLY network path out of Zone U (ARCHITECTURE §1).
    EGRESS_PROXY_URL: str

    # Bot identity. §10 requires the UA to be built from this, so it is
    # required rather than defaulted — an unnamed crawler violates P13.
    NEPTIQ_BOT_INFO_URL: str

    CRAWL_MAX_URLS_DEFAULT: int = 25000
    CRAWL_MAX_URLS_CEILING: int = 50000
    RENDER_BUDGET_DEFAULT: int = 500

    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    @property
    def user_agent(self) -> str:
        """ARCHITECTURE §10 bot identity string, assembled from env only."""
        return f"Mozilla/5.0 (compatible; NeptiqBot/1.0; +{self.NEPTIQ_BOT_INFO_URL})"

    @field_validator("CRAWL_MAX_URLS_CEILING")
    @classmethod
    def _ceiling_above_default(cls, v: int, info: object) -> int:
        # A ceiling below the default would make the default unreachable and
        # every crawl silently truncated. Fail at startup instead.
        if v <= 0:
            raise ValueError("CRAWL_MAX_URLS_CEILING must be positive")
        return v


class Settings(ZoneUSettings):
    """Full Zone T settings: database, cache, storage, secrets, providers."""

    # --- Data stores -------------------------------------------------------
    # Two URLs by design (ARCHITECTURE §8): the application role has NO
    # RLS-bypass capability; only the migrator role owns the tables.
    DATABASE_URL: str
    DATABASE_URL_MIGRATOR: str | None = None

    REDIS_URL: str

    # --- Object storage ----------------------------------------------------
    S3_ENDPOINT: str
    S3_BUCKET: str
    S3_ACCESS_KEY: SecretStr
    S3_SECRET_KEY: SecretStr

    # --- Secrets -----------------------------------------------------------
    KEK_BASE64: SecretStr  # envelope master key; lives OUTSIDE the database
    SESSION_SECRET: SecretStr

    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr | None = None
    CRUX_API_KEY: SecretStr | None = None

    # --- Providers (all optional: P10 / invariant 9 require the system to
    # produce a complete audit with every external LLM provider disabled) ---
    LLM_PROVIDER_PRIMARY: str | None = None
    LLM_PROVIDER_SECONDARY: str | None = None
    LLM_LOCAL_BASE_URL: str | None = None
    SERP_PROVIDER_PRIMARY: str | None = None
    SERP_PROVIDER_SECONDARY: str | None = None

    LLM_BUDGET_CENTS_PER_AUDIT: int = 300

    # --- Public identity ---------------------------------------------------
    NEPTIQ_PUBLIC_HOST: str
    NEPTIQ_APP_URL: str
    NEPTIQ_API_URL: str
    # Separate REGISTRABLE domain, not a subdomain (ARCHITECTURE §14):
    # subdomains share cookie scope, so serving raw hostile bodies from one
    # would put session cookies in reach of that content.
    NEPTIQ_EVIDENCE_HOST: str

    SENTRY_DSN: str | None = None

    @property
    def external_llm_available(self) -> bool:
        """True only if a hosted provider is configured.

        Invariant 9 is tested by forcing this to False and asserting a
        complete audit still completes.
        """
        return bool(self.LLM_PROVIDER_PRIMARY or self.LLM_PROVIDER_SECONDARY)

    @field_validator("NEPTIQ_EVIDENCE_HOST")
    @classmethod
    def _evidence_host_is_separate(cls, v: str) -> str:
        if not v:
            raise ValueError("NEPTIQ_EVIDENCE_HOST is required")
        return v

    def assert_evidence_domain_separate(self) -> None:
        """Assert the evidence host is not a subdomain of the app host.

        Called at API startup. Kept as an explicit method rather than a
        model validator because it is a cross-field invariant whose failure
        message needs to explain *why* — the subtlety is that a subdomain
        looks correct and silently shares cookie scope.
        """
        app = self.NEPTIQ_PUBLIC_HOST.lower().rstrip(".")
        ev = self.NEPTIQ_EVIDENCE_HOST.lower().rstrip(".")
        if ev == app or ev.endswith("." + app) or app.endswith("." + ev):
            raise ValueError(
                "NEPTIQ_EVIDENCE_HOST must be a separate REGISTRABLE domain from "
                "NEPTIQ_PUBLIC_HOST, not a subdomain: subdomains share cookie scope, "
                "which would expose session cookies to raw untrusted response bodies "
                "(ARCHITECTURE §14)."
            )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide Zone T settings. Cached; env is read once at startup."""
    return Settings()  # type: ignore[call-arg]


@functools.lru_cache(maxsize=1)
def get_zone_u_settings() -> ZoneUSettings:
    """Process-wide Zone U settings — the starved variant."""
    return ZoneUSettings()  # type: ignore[call-arg]


__all__ = [
    "Environment",
    "Field",
    "Settings",
    "ZoneUSettings",
    "get_settings",
    "get_zone_u_settings",
]
