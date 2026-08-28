"""neptiq_core — settings, errors, ids, logging, provenance.

The only package every other package may depend on. It deliberately contains
no I/O: no database, no HTTP, no filesystem. That is what allows Zone U
components to import it without acquiring any capability they must not have.
"""

from __future__ import annotations

from neptiq_core.errors import (
    AuthenticationError,
    AuthorizationError,
    BudgetExceededError,
    DegradedModeError,
    IdempotencyConflictError,
    NeptiqError,
    NotFoundError,
    NotMeasurableError,
    QuotaExceededError,
    SsrfBlockedError,
    TaintViolationError,
    ValidationError,
    ZoneViolationError,
)
from neptiq_core.ids import (
    ArtifactId,
    CrawlRunId,
    EvidenceId,
    FindingId,
    OrgId,
    ProjectId,
    SiteId,
    SnapshotId,
    UrlId,
    UserId,
    new_uuid7,
    uuid7_timestamp_ms,
)
from neptiq_core.logging import configure_logging, get_logger
from neptiq_core.provenance import (
    Confidence,
    ExactConfidence,
    IntervalConfidence,
    Method,
    NotMeasurable,
    Provenance,
    ProvenanceModel,
    wilson_interval,
)
from neptiq_core.settings import Settings, ZoneUSettings, get_settings, get_zone_u_settings

__version__ = "0.1.0"

__all__ = [
    "ArtifactId",
    "AuthenticationError",
    "AuthorizationError",
    "BudgetExceededError",
    "Confidence",
    "CrawlRunId",
    "DegradedModeError",
    "EvidenceId",
    "ExactConfidence",
    "FindingId",
    "IdempotencyConflictError",
    "IntervalConfidence",
    "Method",
    "NeptiqError",
    "NotFoundError",
    "NotMeasurable",
    "NotMeasurableError",
    "OrgId",
    "ProjectId",
    "Provenance",
    "ProvenanceModel",
    "QuotaExceededError",
    "Settings",
    "SiteId",
    "SnapshotId",
    "SsrfBlockedError",
    "TaintViolationError",
    "UrlId",
    "UserId",
    "ValidationError",
    "ZoneUSettings",
    "ZoneViolationError",
    "__version__",
    "configure_logging",
    "get_logger",
    "get_settings",
    "get_zone_u_settings",
    "new_uuid7",
    "uuid7_timestamp_ms",
    "wilson_interval",
]
