"""Taint types.

ARCHITECTURE §1: tainted data "may be READ. Tainted data may NEVER become an
instruction, a SQL fragment, a URL to fetch, or a tool argument."

The problem with expressing that as a convention is that a tainted string and
a trusted string are the same type, so no reviewer and no type checker can tell
them apart. This module makes them different types.

``Tainted[T]`` is not a string. It has no ``__str__`` that yields the payload,
it does not implement ``__format__``, and it is not iterable. Every attempt to
use it where a trusted value is expected fails — at type-check time via mypy
(it is not a ``str``), and at runtime via ``TaintViolationError`` for the
dynamic paths mypy cannot see (f-strings, ``%`` formatting, ``.join``).

Extraction is possible, but only through explicitly named methods that state
what safety property the caller is asserting:

    ``.for_display()``   — going to a React text node; React escapes it.
    ``.for_storage()``   — going to a parameterised query as a *value*.
    ``.for_model(...)``  — going into an LLM context, delimited and capped.
    ``.unsafe_raw(reason=...)`` — the audited escape hatch. Requires a reason
                                  string, and CI greps for its use.

The point is not that extraction is impossible. It is that every extraction is
visible in a diff and greppable in CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Generic, NoReturn, TypeVar

from neptiq_core.errors import TaintViolationError

T = TypeVar("T")

# Zero-width and bidirectional control characters. These are the "Trojan
# Source" family: they let text render one way to a human reviewer and parse
# another way to a machine. In a prompt-injection context they also hide
# instructions from anyone eyeballing the evidence viewer.
_INVISIBLE: Final = re.compile(
    "["
    "\u200b-\u200f"  # zero-width space .. RLM
    "\u202a-\u202e"  # LRE .. RLO  (bidi overrides)
    "\u2060-\u2064"  # word joiner .. invisible plus
    "\u2066-\u2069"  # LRI .. PDI
    "\ufeff"  # BOM / zero-width no-break space
    "]"
)

_CONTROL: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Minimum length for the mandatory unsafe_raw() justification.
_MIN_REASON_CHARS: Final = 12


@dataclass(frozen=True, slots=True)
class TaintSource:
    """Where a tainted value came from, for the evidence chain.

    Required, not optional: CONSTITUTION P1 means we must be able to say which
    byte justified a claim, and that is impossible if a tainted value arrives
    without an origin.
    """

    kind: str  # "http_body" | "http_header" | "dom_text" | "json_ld" | "api_response" | "upload"
    evidence_id: str | None = None
    url: str | None = None
    selector: str | None = None
    byte_offset: int | None = None


class Tainted(Generic[T]):
    """A value originating outside the trust boundary.

    Deliberately NOT a str subclass. Subclassing str would make every existing
    string operation silently succeed, which defeats the entire purpose.
    """

    __slots__ = ("_source", "_value")

    def __init__(self, value: T, source: TaintSource) -> None:
        self._value = value
        self._source = source

    # --- Introspection that does not leak the payload ---------------------

    @property
    def source(self) -> TaintSource:
        return self._source

    def __len__(self) -> int:
        v = self._value
        return len(v) if isinstance(v, str | bytes | list | dict | tuple) else 0

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        # Length and origin only. Never the content: a repr ends up in logs,
        # tracebacks and Sentry titles, all of which are trust-elevating sinks.
        return f"<Tainted {self._source.kind} len={len(self)}>"

    # --- Blocked coercions -------------------------------------------------
    #
    # These exist so the failure is loud and specific rather than a confusing
    # TypeError three frames away.

    def _blocked(self, op: str) -> NoReturn:
        raise TaintViolationError(
            f"refused to {op} a Tainted value from {self._source.kind}. "
            "Use .for_display(), .for_storage(), .for_model() or, with an audited "
            "reason, .unsafe_raw(reason=...). See ARCHITECTURE §1."
        )

    # PLE0307: ruff objects that __str__ does not return str. That is precisely
    # the design — a Tainted value must not be silently stringifiable, because
    # str() is the most common accidental path from hostile content into a log
    # line, an SQL fragment or a prompt. The annotation is NoReturn and the call
    # always raises.
    def __str__(self) -> str:  # noqa: PLE0307
        self._blocked("str()")

    def __format__(self, spec: str) -> str:
        self._blocked("format/f-string")

    def __iter__(self) -> NoReturn:
        self._blocked("iterate")

    def __add__(self, other: object) -> NoReturn:
        self._blocked("concatenate")

    def __radd__(self, other: object) -> NoReturn:
        self._blocked("concatenate")

    def __eq__(self, other: object) -> bool:
        # Equality is permitted against another Tainted only. Comparing to a
        # trusted literal is usually an attempt at ad-hoc validation, which
        # belongs in a validator, not scattered at call sites.
        if isinstance(other, Tainted):
            return bool(self._value == other._value)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("tainted", self._source.kind, repr(self._value)))

    # --- Audited extraction ------------------------------------------------

    def for_display(self) -> T:
        """Extract for rendering as TEXT in a React node.

        Safe only because invariant 5 forbids ``dangerouslySetInnerHTML``
        anywhere in apps/web, and CI enforces it. React escapes text children,
        so the payload cannot become markup. If that invariant is ever relaxed,
        every caller of this method becomes an XSS sink.
        """
        return self._sanitised()

    def for_storage(self) -> T:
        """Extract to pass as a BOUND PARAMETER to a parameterised query.

        Never for string-building SQL. SQLAlchemy's text() with bound params or
        the ORM are the only permitted sinks; ``f"... {value}"`` into SQL is a
        taint violation regardless of this method being used.
        """
        return self._sanitised()

    def for_model(self, *, max_chars: int = 4000) -> str:
        """Extract for inclusion in an LLM context, delimited and capped.

        ARCHITECTURE §14: injection is handled "structurally, not by prompt
        wording: delimited, escaped, length-capped tainted fields". The
        delimiter is a fixed sentinel the prompt template refers to, and any
        occurrence of the sentinel inside the payload is neutralised so hostile
        content cannot close the delimiter and escape into instruction
        position.
        """
        raw = self._sanitised()
        text = raw if isinstance(raw, str) else repr(raw)
        text = text.replace(_SENTINEL_OPEN, "[[removed]]").replace(_SENTINEL_CLOSE, "[[removed]]")
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[TRUNCATED at {max_chars} chars]"
        return f"{_SENTINEL_OPEN}\n{text}\n{_SENTINEL_CLOSE}"

    def unsafe_raw(self, *, reason: str) -> T:
        """The audited escape hatch.

        ``reason`` is mandatory and must be non-trivial. CI greps for
        ``unsafe_raw`` and requires an accompanying ``# taint-ok:`` comment, so
        each use is a deliberate, reviewed decision rather than an accident.
        """
        if not reason or len(reason) < _MIN_REASON_CHARS:
            raise TaintViolationError(
                "unsafe_raw() requires a substantive reason describing why raw access is safe here"
            )
        return self._value

    def _sanitised(self) -> T:
        v = self._value
        if isinstance(v, str):
            return _CONTROL.sub("", _INVISIBLE.sub("", v))  # type: ignore[return-value]
        return v

    def map(self, fn: Any) -> Tainted[Any]:
        """Apply a pure function, preserving taint.

        Transformation must never launder provenance: a parsed, trimmed,
        lower-cased hostile string is still hostile.
        """
        return Tainted(fn(self._value), self._source)


_SENTINEL_OPEN: Final = "<<<NEPTIQ_UNTRUSTED_CONTENT>>>"
_SENTINEL_CLOSE: Final = "<<<END_NEPTIQ_UNTRUSTED_CONTENT>>>"


def taint(value: T, *, kind: str, **kw: Any) -> Tainted[T]:
    """Wrap a value arriving from outside the trust boundary."""
    return Tainted(value, TaintSource(kind=kind, **kw))


def strip_invisible(text: str) -> str:
    """Remove zero-width and bidi-override characters.

    Exposed separately because the parser needs it on trusted-side text too:
    a URL or a canonical tag containing a zero-width space must not compare
    equal-looking-but-unequal to the clean form.
    """
    return _INVISIBLE.sub("", text)


__all__ = ["TaintSource", "Tainted", "strip_invisible", "taint"]
