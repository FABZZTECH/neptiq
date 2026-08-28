"""Typed error hierarchy, shaped for RFC 9457 problem responses.

ARCHITECTURE §9: "RFC 9457 errors". The API layer translates these into
``application/problem+json``. Errors carry a stable machine-readable ``code``
because clients — including our own generated TypeScript client — must branch
on something that does not change when we reword a human message.

Design rule: an error never carries tainted content in ``detail`` without it
being explicitly marked. CONSTITUTION P6 makes all external content hostile,
and an error message is one of the classic paths by which hostile content
reaches a log aggregator, a Sentry issue title, or a model context.
"""

from __future__ import annotations

from typing import Any


class NeptiqError(Exception):
    """Base for every deliberate NEPTIQ failure.

    ``status`` and ``code`` are class attributes so that subclasses read as
    declarations rather than constructors full of magic numbers.
    """

    status: int = 500
    code: str = "internal_error"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail or self.title
        self.extra = extra
        super().__init__(self.detail)

    def as_problem(self, instance: str | None = None) -> dict[str, Any]:
        """Render as an RFC 9457 problem document body.

        ``type`` is a relative URI reference under /problems/; it is
        deliberately NOT an absolute URL, because invariant 6 forbids
        hardcoding hostnames in source. The API layer resolves it against
        NEPTIQ_APP_URL at response time.
        """
        body: dict[str, Any] = {
            "type": f"/problems/{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }
        if instance is not None:
            body["instance"] = instance
        body.update(self.extra)
        return body


# --- Client-side (4xx) -----------------------------------------------------


class ValidationError(NeptiqError):
    status = 422
    code = "validation_failed"
    title = "Request failed validation"


class NotFoundError(NeptiqError):
    status = 404
    code = "not_found"
    title = "Resource not found"


class AuthenticationError(NeptiqError):
    status = 401
    code = "authentication_required"
    title = "Authentication required"


class AuthorizationError(NeptiqError):
    status = 403
    code = "forbidden"
    title = "Not permitted"


class IdempotencyConflictError(NeptiqError):
    """Same Idempotency-Key replayed with a different request body.

    ARCHITECTURE §9 stores responses for 24 hours. A key reused with different
    parameters is a client bug we must surface loudly rather than silently
    returning the first response.
    """

    status = 409
    code = "idempotency_conflict"
    title = "Idempotency-Key reused with a different request body"


class QuotaExceededError(NeptiqError):
    status = 429
    code = "quota_exceeded"
    title = "Quota or rate limit exceeded"


# --- Zone / security -------------------------------------------------------


class ZoneViolationError(NeptiqError):
    """A Zone U component attempted something only Zone T may do.

    This should be unreachable in shipped code — CI invariant 1 rejects the
    import graph that would make it possible. It exists as a runtime backstop
    because "unreachable" and "actually unreachable" differ.
    """

    status = 500
    code = "zone_violation"
    title = "Trust zone violation"


class SsrfBlockedError(NeptiqError):
    """The egress proxy refused a destination address.

    ARCHITECTURE §14. Carries the *reason* but never the resolved internal
    address, which would itself be an information disclosure.
    """

    status = 400
    code = "ssrf_blocked"
    title = "Destination address is not permitted"


class TaintViolationError(NeptiqError):
    """Tainted content was about to be used as an instruction, SQL fragment,
    URL to fetch, or tool argument.

    ARCHITECTURE §1 forbids exactly this. Raised by the taint types in
    neptiq_security rather than being caught and worked around.
    """

    status = 500
    code = "taint_violation"
    title = "Tainted value used in a trusted position"


# --- Capability / degradation ---------------------------------------------


class DegradedModeError(NeptiqError):
    """A capability is unavailable and no fallback remains.

    CONSTITUTION P10 requires a defined degraded mode rather than a crash, so
    this is raised only after the ordered fallback chain in ARCHITECTURE §11
    is exhausted. Callers are expected to surface the visible banner, not to
    retry blindly.
    """

    status = 503
    code = "degraded_mode"
    title = "Capability unavailable; system is in degraded mode"


class NotMeasurableError(NeptiqError):
    """A quantity was requested that NEPTIQ cannot honestly measure.

    CONSTITUTION P11 and the GEO Honesty Charter. Raising this is always
    correct behaviour; converting it into a confident number never is.
    """

    status = 422
    code = "not_measurable"
    title = "Not measurable by NEPTIQ"


class BudgetExceededError(NeptiqError):
    """An LLM or crawl budget ceiling was reached.

    CONSTITUTION P9 makes cost a first-class datum; a budget breach is a
    normal, expected, reportable condition, not an exception to swallow.
    """

    status = 402
    code = "budget_exceeded"
    title = "Budget ceiling reached"
