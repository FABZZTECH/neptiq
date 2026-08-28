"""Base response schemas.

Invariant 4 (ARCHITECTURE §6): "Every response model containing a derived
number must inherit ``ProvenanceModel``." ``ProvenanceModel`` itself lives in
neptiq_core so that workers can construct provenance without importing FastAPI.

This module adds the API-layer conventions on top: camelCase aliasing for the
wire (the generated TypeScript client is idiomatic TS, the Python is idiomatic
Python, and neither has to compromise), and cursor pagination.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from neptiq_core.provenance import Provenance, ProvenanceModel

T = TypeVar("T")


class ApiModel(BaseModel):
    """Base for every request and response body.

    ``extra="forbid"`` on requests is a security property, not tidiness: it
    means a client cannot smuggle an unexpected field that a later version of
    the model might start honouring (mass-assignment).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class DerivedValue(ApiModel, ProvenanceModel):
    """Any single derived number, carrying its own provenance.

    Used where a response has one headline figure. Composite responses inherit
    ProvenanceModel directly so the provenance describes the whole object.
    """

    value: float | int | None = Field(
        default=None,
        description=(
            "Null when confidence.kind == 'not_measurable'. Clients must render "
            "the not-measurable label, never 0 or a dash implying zero "
            "(CONSTITUTION P11)."
        ),
    )
    unit: str | None = None


class Page(ApiModel, Generic[T]):
    """Opaque cursor pagination (ARCHITECTURE §9).

    The cursor is opaque by contract: clients must not construct or decode it.
    Offset pagination is deliberately not offered — with append-only tables
    under continuous crawl writes, offsets skip and duplicate rows.
    """

    items: list[T]
    next_cursor: str | None = Field(
        default=None, description="Pass as ?cursor= to fetch the next page. Opaque; do not parse."
    )


class ProblemDetail(ApiModel):
    """RFC 9457 problem document (ARCHITECTURE §9)."""

    model_config = ConfigDict(alias_generator=None, populate_by_name=True, extra="allow")

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None


__all__ = ["ApiModel", "DerivedValue", "Page", "ProblemDetail", "Provenance", "ProvenanceModel"]
