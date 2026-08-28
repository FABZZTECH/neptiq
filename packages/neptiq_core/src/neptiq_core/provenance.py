"""Provenance and confidence representation.

CONSTITUTION P1 (evidence before opinion), P7 (uncertainty displayed) and P11
(honest non-measurement) together mean a derived number is never a bare float.
ARCHITECTURE §9 fixes the wire shape:

    provenance: { method, source_ids[], computed_at, engine_version, confidence }

and invariant 4 requires every response model containing a derived number to
inherit ``ProvenanceModel``. That inheritance is checked in CI by
tools/check_provenance.py, because a reviewer will not reliably notice a new
float field on a 40-field schema.

The ``Confidence`` union is the interesting part. Three *structurally
different* shapes, not one number with a nullable interval:

  * ``ExactConfidence``    — a deterministic check. It is or it is not.
  * ``IntervalConfidence`` — sampled measurement, carries n and the interval.
                             The GEO Charter requires n and the interval be
                             shown, so they are non-optional fields here.
  * ``NotMeasurable``      — the honest answer. P11 makes this a first-class
                             value, so it cannot be coerced into a score.

Making these separate types means "confidence 0.5" cannot be written for a
thing that was never sampled, and a not-measurable quantity cannot be summed.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExactConfidence(BaseModel):
    """A deterministic computation. No uncertainty to represent."""

    model_config = ConfigDict(frozen=True)
    kind: Literal["exact"] = "exact"


class IntervalConfidence(BaseModel):
    """A sampled measurement with its parameters.

    GEO Honesty Charter: "the UI states n and the interval". Both are required.
    ``level`` defaults to 0.95 but is explicit on the wire so a future change
    cannot silently reinterpret stored records.
    """

    model_config = ConfigDict(frozen=True)
    kind: Literal["interval"] = "interval"
    point: float = Field(description="Point estimate, e.g. an appearance rate in [0,1].")
    low: float = Field(description="Lower bound of the confidence interval.")
    high: float = Field(description="Upper bound of the confidence interval.")
    n: int = Field(ge=1, description="Number of samples the estimate is drawn from.")
    level: float = Field(default=0.95, gt=0.0, lt=1.0)
    method: str = Field(default="wilson", description="Interval construction method.")


class NotMeasurable(BaseModel):
    """The quantity cannot be honestly measured.

    CONSTITUTION P11. ``proxy`` optionally names the best honest substitute,
    which the UI must label as a proxy — never render as the thing itself.
    """

    model_config = ConfigDict(frozen=True)
    kind: Literal["not_measurable"] = "not_measurable"
    reason: str
    proxy: str | None = None


Confidence = Annotated[
    ExactConfidence | IntervalConfidence | NotMeasurable,
    Field(discriminator="kind"),
]


class Method(BaseModel):
    """How a value was produced.

    ``rule_id``/``rule_version`` are present for rule-engine output;
    ``model_id``/``prompt_version`` for anything a model touched. Both being
    absent means a plain deterministic computation. A value with a
    ``model_id`` is, per P2, never a fact about the world — the UI uses this
    field to decide whether it may be presented as one.
    """

    model_config = ConfigDict(frozen=True)
    name: str = Field(description="Stable name of the computation, e.g. 'canonical_conflict'.")
    kind: Literal["deterministic", "sampled", "model_assisted"] = "deterministic"
    rule_id: str | None = None
    rule_version: int | None = None
    model_id: str | None = None
    prompt_version: str | None = None


class Provenance(BaseModel):
    """The full backwards trace for one derived value.

    CONSTITUTION §4 core promise: "Every claim traces backwards to the byte
    that justified it". ``source_ids`` is that trace and is required to be
    non-empty for any derived value — a derived number with no sources is
    exactly the unsupported claim P1 forbids.
    """

    model_config = ConfigDict(frozen=True)
    method: Method
    source_ids: list[UUID] = Field(
        min_length=1,
        description="Evidence / observation ids justifying this value. Never empty.",
    )
    computed_at: datetime
    engine_version: str = Field(description="Version of the code that computed the value.")
    confidence: Confidence

    @classmethod
    def deterministic(
        cls,
        *,
        name: str,
        source_ids: list[UUID],
        engine_version: str,
        rule_id: str | None = None,
        rule_version: int | None = None,
    ) -> Provenance:
        return cls(
            method=Method(
                name=name, kind="deterministic", rule_id=rule_id, rule_version=rule_version
            ),
            source_ids=source_ids,
            computed_at=datetime.now(UTC),
            engine_version=engine_version,
            confidence=ExactConfidence(),
        )


class ProvenanceModel(BaseModel):
    """Base class for any response model carrying a derived number.

    Invariant 4. Enforced by tools/check_provenance.py.
    """

    provenance: Provenance


def wilson_interval(successes: int, n: int, level: float = 0.95) -> IntervalConfidence:
    """Wilson score interval for a binomial proportion.

    Chosen over the normal approximation because appearance rates in the GEO
    charter are routinely near 0 or 1, where the normal approximation produces
    bounds outside [0,1] — i.e. visibly nonsense output in the UI. Wilson stays
    inside the unit interval and behaves at small n, which matters because
    n>=96 is the floor, not the typical case, for a new prompt set.

    Deterministic and pure: property-tested in tests/unit.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if not 0 <= successes <= n:
        raise ValueError("successes must be within [0, n]")
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0,1)")

    # Two-sided z via the inverse error function; avoids a scipy dependency for
    # one number, and P10 discourages load-bearing dependencies generally.
    z = math.sqrt(2.0) * _erfinv(level)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    return IntervalConfidence(point=p, low=low, high=high, n=n, level=level, method="wilson")


def _erfinv(x: float) -> float:
    """Inverse error function via Newton refinement on a rational seed.

    Accurate to well under 1e-10 across the range we use, which is far tighter
    than the sampling error it is applied to.
    """
    if not -1.0 < x < 1.0:
        raise ValueError("x must be in (-1,1)")
    # Winitzki initial approximation.
    a = 0.147
    ln1mx2 = math.log(1.0 - x * x)
    term1 = 2.0 / (math.pi * a) + ln1mx2 / 2.0
    y = math.copysign(math.sqrt(math.sqrt(term1 * term1 - ln1mx2 / a) - term1), x)
    # Two Newton steps against erf.
    for _ in range(3):
        err = math.erf(y) - x
        deriv = 2.0 / math.sqrt(math.pi) * math.exp(-y * y)
        if deriv == 0.0:
            break
        y -= err / deriv
    return y
