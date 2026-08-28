"""Dual-agent robots.txt evaluation.

ARCHITECTURE §10:

    "Robots is evaluated TWICE: as NeptiqBot (governs whether we fetch) and as
     Googlebot (governs whether we report an indexability problem). Conflating
     these is the most common false positive in commercial SEO tools."

The two questions are genuinely independent:

  * ``may_fetch``  — a P13 obligation. If robots.txt disallows NeptiqBot, we do
    not fetch, full stop. This has nothing to do with the customer's SEO.
  * ``googlebot_allowed`` — a finding input. If robots.txt disallows Googlebot
    from a URL the customer wants indexed, that is a real problem worth
    reporting.

Conflating them produces both error directions. A site that blocks all
non-major crawlers but welcomes Googlebot generates a flood of bogus
"blocked by robots" findings. A site that allows everything except Googlebot
generates none, having been crawled happily.

CONSTITUTION §7 lists "Robots.txt evaluation" among the things a language model
must never decide, so this is entirely deterministic, delegating matching to
``protego`` (which implements Google's documented longest-match semantics).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from protego import Protego

# The user-agent product tokens each evaluation runs under. These are public
# crawler identifiers, not credentials; ruff's S105 heuristic fires on the word
# "token", hence the targeted noqa rather than renaming a domain term.
NEPTIQ_UA_TOKEN: Final = "NeptiqBot"  # noqa: S105
GOOGLEBOT_UA_TOKEN: Final = "Googlebot"  # noqa: S105

# HTTP status boundaries, named so the branch conditions read as intent.
_HTTP_OK: Final = 200
_HTTP_REDIRECT: Final = 300
_HTTP_SERVER_ERROR: Final = 500

# Conservative default when robots.txt could not be retrieved at all.
# Google's documented behaviour: a 5xx or timeout on robots.txt means treat the
# site as fully disallowed (temporarily). We mirror that for may_fetch because
# P13 requires conservative politeness, but we deliberately do NOT report an
# indexability finding from it, because a transient 503 on robots.txt is not
# evidence of a customer misconfiguration.
_UNREACHABLE_MEANS_DISALLOW: Final = True


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    """The two independent answers, plus why.

    ``report_indexability_issue`` exists so the caller cannot accidentally
    derive the finding from ``may_fetch``. It is False whenever the answer
    would be an artefact of our own identity or of a fetch failure rather than
    of the site's configuration.
    """

    may_fetch: bool
    googlebot_allowed: bool
    crawl_delay_seconds: float | None
    matched_agent: str | None
    reason: str

    @property
    def report_indexability_issue(self) -> bool:
        return not self.googlebot_allowed


@dataclass(frozen=True, slots=True)
class RobotsDocument:
    """A parsed robots.txt, or the record of why we have none.

    ``status`` is the HTTP status of the robots.txt fetch. It matters: 200 with
    an empty body means "allow all", 404 means "allow all", 503 means "disallow
    all, temporarily", and those are three different situations that a boolean
    ``exists`` flag would flatten.
    """

    status: int | None
    body: str | None
    fetch_error: str | None = None

    @property
    def usable(self) -> bool:
        return (
            self.status is not None
            and _HTTP_OK <= self.status < _HTTP_REDIRECT
            and self.body is not None
        )


class RobotsEvaluator:
    """Evaluates one site's robots.txt under both agent identities.

    Constructed once per site per crawl and reused across every URL, because
    re-parsing robots.txt 25,000 times is measurable at our target scale.
    """

    __slots__ = ("_document", "_parser")

    def __init__(self, document: RobotsDocument) -> None:
        self._document = document
        self._parser: Protego | None = None
        if document.usable and document.body is not None:
            # Protego is tolerant of malformed input by design, which is what
            # we want: fixture site 11 is "hostile robots.txt" and must not
            # crash the crawler.
            self._parser = Protego.parse(document.body)

    def evaluate(self, url: str) -> RobotsDecision:
        """Return the dual decision for ``url``.

        ``url`` must already be normalised by neptiq_url; robots matching is
        path-and-query sensitive, so matching a non-canonical spelling would
        give a different answer than the one the origin intends.
        """
        doc = self._document

        # Case 1: robots.txt unreachable / server error.
        if not doc.usable:
            transient = doc.status is None or doc.status >= _HTTP_SERVER_ERROR
            if transient and _UNREACHABLE_MEANS_DISALLOW:
                return RobotsDecision(
                    may_fetch=False,
                    # Not a finding: we could not observe the site's intent, so
                    # asserting an indexability problem would violate P1.
                    googlebot_allowed=True,
                    crawl_delay_seconds=None,
                    matched_agent=None,
                    reason=(
                        f"robots.txt unreachable (status={doc.status}, "
                        f"error={doc.fetch_error}); treating as disallow for fetching "
                        "per Google's documented 5xx behaviour, and making no "
                        "indexability claim since site intent was not observed"
                    ),
                )
            # 4xx (including 404) means no restrictions.
            return RobotsDecision(
                may_fetch=True,
                googlebot_allowed=True,
                crawl_delay_seconds=None,
                matched_agent=None,
                reason=f"no robots.txt (status={doc.status}); allow all",
            )

        assert self._parser is not None  # usable implies a parser was built

        # Case 2: parse and ask twice, under two identities.
        may_fetch = bool(self._parser.can_fetch(url, NEPTIQ_UA_TOKEN))
        googlebot_allowed = bool(self._parser.can_fetch(url, GOOGLEBOT_UA_TOKEN))

        # protego ships no py.typed, so crawl_delay() is Any at this boundary.
        # Coerced immediately to float | None so nothing downstream inherits
        # Any from an untyped third-party return.
        delay: object = self._parser.crawl_delay(NEPTIQ_UA_TOKEN)
        crawl_delay = float(delay) if isinstance(delay, int | float) else None

        return RobotsDecision(
            may_fetch=may_fetch,
            googlebot_allowed=googlebot_allowed,
            crawl_delay_seconds=crawl_delay,
            matched_agent=NEPTIQ_UA_TOKEN,
            reason=(
                f"evaluated robots.txt twice: NeptiqBot={'allow' if may_fetch else 'disallow'}, "
                f"Googlebot={'allow' if googlebot_allowed else 'disallow'}"
            ),
        )

    def sitemaps(self) -> list[str]:
        """Sitemap URLs declared in robots.txt.

        Returned as-is; the caller must normalise and SSRF-validate them. A
        Sitemap: directive is attacker-controlled content on an arbitrary site,
        so treating it as a trusted URL to fetch would violate §1.
        """
        if self._parser is None:
            return []
        return list(self._parser.sitemaps or [])


def evaluate_url(document: RobotsDocument, url: str) -> RobotsDecision:
    """Convenience single-shot evaluation. Prefer ``RobotsEvaluator`` in loops."""
    return RobotsEvaluator(document).evaluate(url)


__all__ = [
    "GOOGLEBOT_UA_TOKEN",
    "NEPTIQ_UA_TOKEN",
    "RobotsDecision",
    "RobotsDocument",
    "RobotsEvaluator",
    "evaluate_url",
]
