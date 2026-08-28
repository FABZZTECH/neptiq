"""uuidv7 identifiers.

ARCHITECTURE §8: "``uuidv7()`` primary keys". PostgreSQL 18 generates these
natively server-side, which is the normal path. This module exists for the
cases where the application must know the id *before* the INSERT — chiefly
idempotency keys and content-addressed blob naming in Zone U, which has no
database connection at all and therefore cannot ask Postgres for one.

Why uuidv7 rather than uuid4: the leading 48 bits are a millisecond Unix
timestamp, so ids sort chronologically. That gives B-tree locality on insert
for append-only tables (page_snapshots, links, evidence, cost_records) which
are exactly the tables that grow without bound. uuid4 would scatter inserts
across the whole index and turn the evidence ledger into a write-amplification
problem at 50k URLs per crawl.
"""

from __future__ import annotations

import uuid
from typing import Final, NewType

import uuid_utils

UUID_VERSION_7: Final = 7
# UUIDv7 layout: 48-bit big-endian millisecond timestamp in the most
# significant bits, so shifting right by the remaining 80 bits recovers it.
_TIMESTAMP_SHIFT_BITS: Final = 80

# Distinct types per entity class. These are NewType over uuid.UUID rather than
# bare UUID so that mypy rejects passing an OrgId where a ProjectId is wanted.
# Tenant-scoped confusion is the single most dangerous class of bug in a
# multi-tenant system; the type checker should catch it before RLS has to.
OrgId = NewType("OrgId", uuid.UUID)
UserId = NewType("UserId", uuid.UUID)
ProjectId = NewType("ProjectId", uuid.UUID)
SiteId = NewType("SiteId", uuid.UUID)
UrlId = NewType("UrlId", uuid.UUID)
CrawlRunId = NewType("CrawlRunId", uuid.UUID)
SnapshotId = NewType("SnapshotId", uuid.UUID)
FindingId = NewType("FindingId", uuid.UUID)
EvidenceId = NewType("EvidenceId", uuid.UUID)
ArtifactId = NewType("ArtifactId", uuid.UUID)
DeploymentId = NewType("DeploymentId", uuid.UUID)
WorkflowRunId = NewType("WorkflowRunId", uuid.UUID)
JobId = NewType("JobId", uuid.UUID)
LlmRunId = NewType("LlmRunId", uuid.UUID)
CostRecordId = NewType("CostRecordId", uuid.UUID)


def new_uuid7() -> uuid.UUID:
    """Return a fresh time-ordered UUIDv7 as a stdlib ``uuid.UUID``.

    ``uuid_utils`` returns its own UUID class, which is not a ``uuid.UUID``
    subclass and does not satisfy SQLAlchemy's or Pydantic's UUID handling.
    Round-tripping through ``.bytes`` normalises it and costs nothing
    measurable relative to any statement we would then execute.
    """
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Extract the embedded millisecond timestamp from a UUIDv7.

    Raises ``ValueError`` if ``value`` is not version 7 — an important guard,
    because silently returning a nonsense timestamp for a uuid4 would produce
    plausible-looking but wrong ordering in audit output, and CONSTITUTION P4
    requires that the past be queryable exactly as it was recorded.
    """
    if value.version != UUID_VERSION_7:
        raise ValueError(f"expected a UUIDv7, got version {value.version}")
    return value.int >> _TIMESTAMP_SHIFT_BITS
