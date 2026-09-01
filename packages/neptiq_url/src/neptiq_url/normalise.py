"""Pure URL normalisation.

ARCHITECTURE §10 specifies the exact transform list and one hard property:

    "Must be injective on the fixture corpus — a collision silently corrupts
     both the frontier and the evidence ledger."

That is the whole reason this is a separate package with no dependencies on
anything that does I/O. It is a pure function, property-tested with Hypothesis,
and it is the definition of URL identity everywhere in the system:
``urls.url_hash`` is sha256 of the output of ``normalise()``.

The transform list, in the order §10 gives it:

  1. lowercase scheme and host
  2. IDN to punycode
  3. default ports removed
  4. dot segments resolved
  5. percent-encoding normalised to uppercase hex
  6. tracking parameters stripped
  7. fragment removed

Two decisions worth stating because they are the ones that break injectivity
if done naively:

* **Query parameter order is preserved, not sorted.** Sorting looks tidy and is
  wrong: for a non-trivial number of real sites ``?a=1&b=2`` and ``?b=2&a=1``
  return different bodies (ordered filters, signed URLs, some CMS routers).
  Sorting would map two distinct resources onto one hash — precisely the
  collision §10 forbids. We strip known-inert tracking params only.

* **Empty-value vs valueless parameters are distinguished.** ``?a`` and ``?a=``
  are preserved as written, because they are distinguishable at the origin and
  some frameworks treat them differently.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

import idna

# Schemes we will ever normalise. Anything else is rejected rather than
# silently passed through: a javascript: or data: URL reaching the frontier is
# a security problem, not a normalisation problem.
ALLOWED_SCHEMES: Final = frozenset({"http", "https"})

DEFAULT_PORTS: Final = {"http": 80, "https": 443}

# RFC-defined limits, named so the checks below read as the standard they cite.
MAX_URL_LENGTH: Final = 4096  # our own cap; longer URLs are not real crawl targets
MAX_HOST_LENGTH: Final = 253  # RFC 1035 §2.3.4 total length of a domain name
MAX_LABEL_LENGTH: Final = 63  # RFC 1035 §2.3.4 single label
MAX_PORT: Final = 65535  # RFC 6335
ASCII_MAX: Final = 127

# Tracking parameters stripped per §10. Deliberately conservative: every entry
# here is inert with respect to the response body at the origin. Anything
# whose removal could change what the server returns must NOT be added, since
# that would collapse two distinct resources into one hash.
TRACKING_PARAMS: Final = frozenset(
    {
        # Google / analytics
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "utm_creative_format",
        "utm_marketing_tactic",
        "gclid",
        "gclsrc",
        "dclid",
        "gbraid",
        "wbraid",
        "gad_source",
        "gad_campaignid",
        "_ga",
        "_gl",
        # Microsoft / Meta / others
        "msclkid",
        "fbclid",
        "igshid",
        "twclid",
        "ttclid",
        "li_fat_id",
        "epik",
        "rdt_cid",
        "yclid",
        "wickedid",
        "sccid",
        # Email / marketing platforms
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "vero_conv",
        "vero_id",
        "hsa_acc",
        "hsa_cam",
        "hsa_grp",
        "hsa_ad",
        "hsa_src",
        "hsa_tgt",
        "hsa_kw",
        "hsa_mt",
        "hsa_net",
        "hsa_ver",
        "_hsenc",
        "_hsmi",
        "hsCtaTracking",
        # Misc referral noise
        "ref_src",
        "ref_url",
        "s_kwcid",
        "icid",
        "trk",
        "trkCampaign",
    }
)

# Characters that must never be percent-decoded during normalisation, because
# decoding them changes the URL's structural meaning rather than its spelling.
# %2F decoded to "/" would turn one path segment into two; %3F into "?" would
# invent a query string. RFC 3986 calls these reserved for exactly this reason.
_STRUCTURAL = frozenset("/?#[]@:!$&'()*+,;=%")

_PCT = re.compile(r"%([0-9A-Fa-f]{2})")

# Unreserved per RFC 3986 §2.3 — safe to decode, and canonically SHOULD be
# decoded so that %41 and A hash identically.
_UNRESERVED = re.compile(r"^[A-Za-z0-9\-._~]$")


class UrlNormalisationError(ValueError):
    """The input is not a URL we are willing to represent.

    Raised rather than returning a best-effort string: a frontier entry we
    cannot canonicalise is a frontier entry we must not store.
    """


def _normalise_percent_encoding(value: str, *, safe: str) -> str:
    """Canonicalise percent-encoding: uppercase hex, decode unreserved only.

    §10 requires "percent-encoding normalised to uppercase hex". We also decode
    needlessly-encoded unreserved characters, because %7E and ~ denote the same
    resource and leaving both spellings alive would let one URL enter the
    frontier twice under two hashes — a duplicate crawl and a split history.
    """

    def _decode_unreserved(m: re.Match[str]) -> str:
        ch = chr(int(m.group(1), 16))
        if _UNRESERVED.match(ch):
            return ch
        return "%" + m.group(1).upper()

    stepped = _PCT.sub(_decode_unreserved, value)

    # Re-encode anything that must be encoded but was left literal, without
    # touching existing valid escapes (already uppercased above).
    out: list[str] = []
    i = 0
    while i < len(stepped):
        ch = stepped[i]
        if ch == "%" and _PCT.match(stepped, i):
            out.append(stepped[i : i + 3])
            i += 3
            continue
        if ch in safe or _UNRESERVED.match(ch):
            out.append(ch)
        else:
            out.append(quote(ch, safe=""))
        i += 1
    return "".join(out)


def _resolve_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 remove_dot_segments.

    Implemented explicitly rather than via ``posixpath.normpath`` because
    normpath collapses a trailing slash, and ``/a/`` and ``/a`` are genuinely
    different resources at most origins (one commonly redirects to the other,
    which is itself a finding we want to detect, not erase).
    """
    if not path:
        return ""
    trailing_slash = path.endswith("/")
    segments = path.split("/")
    out: list[str] = []
    for seg in segments:
        if seg == ".":
            continue
        if seg == "..":
            if out and out[-1] != "":
                out.pop()
            continue
        out.append(seg)
    result = "/".join(out)
    if trailing_slash and not result.endswith("/"):
        result += "/"
    if not result.startswith("/"):
        result = "/" + result.lstrip("/")
    return result


def _normalise_host(host: str) -> str:
    """Lowercase, IDN-to-punycode, strip trailing dot, reject the malformed.

    A trailing dot is stripped because ``example.com.`` and ``example.com`` are
    the same host to every server but different strings to a hash function.
    """
    if not host:
        raise UrlNormalisationError("URL has no host")

    host = host.strip().rstrip(".").lower()
    if not host:
        raise UrlNormalisationError("URL host is empty after normalisation")

    # Already-punycode or plain ASCII hosts pass through idna.encode's
    # uts46 path unchanged; non-ASCII gets converted (§10 step 2).
    try:
        if any(ord(c) > ASCII_MAX for c in host):
            host = idna.encode(host, uts46=True).decode("ascii")
        else:
            # Validate shape without rewriting; idna rejects e.g. empty labels.
            for label in host.split("."):
                if not label:
                    raise UrlNormalisationError(f"empty label in host {host!r}")
                if len(label) > MAX_LABEL_LENGTH:
                    raise UrlNormalisationError(f"host label too long in {host!r}")
    except idna.IDNAError as exc:
        raise UrlNormalisationError(f"invalid internationalised host: {exc}") from exc

    if len(host) > MAX_HOST_LENGTH:
        raise UrlNormalisationError(f"host exceeds {MAX_HOST_LENGTH} characters")
    return host


def _normalise_query(query: str, *, strip_tracking: bool) -> str:
    """Strip tracking params, canonicalise encoding, PRESERVE ORDER.

    See the module docstring: order preservation is a correctness requirement,
    not a stylistic choice.
    """
    if not query:
        return ""

    # keep_blank_values so that ?a= survives; we then distinguish ?a from ?a=
    # by inspecting the raw text, which parse_qsl discards.
    pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=False)
    raw_parts = [p for p in query.split("&") if p != ""]
    valueless = {p for p in raw_parts if "=" not in p}

    out: list[str] = []
    for key, value in pairs:
        if strip_tracking and key.lower() in TRACKING_PARAMS:
            continue
        k = _normalise_percent_encoding(quote(unquote(key), safe=""), safe="")
        if key in valueless and value == "":
            out.append(k)
            continue
        v = _normalise_percent_encoding(quote(unquote(value), safe=""), safe="")
        out.append(f"{k}={v}")
    return "&".join(out)


def normalise(url: str, *, strip_tracking: bool = True) -> str:
    """Return the canonical form of ``url``.

    Pure. Deterministic. Idempotent — ``normalise(normalise(u)) ==
    normalise(u)`` is a property test, because a non-idempotent normaliser
    means the hash of a URL depends on how many times it has been through the
    pipeline, which is a data-corruption bug waiting for a retry to trigger it.

    Raises ``UrlNormalisationError`` for anything not an absolute http(s) URL.
    """
    if not isinstance(url, str):  # pragma: no cover - defensive, mypy-unreachable
        raise UrlNormalisationError("url must be a string")

    candidate = url.strip()
    if not candidate:
        raise UrlNormalisationError("empty URL")

    # Control characters are stripped before parsing. A tab or newline inside a
    # URL is how a hostile page smuggles a different destination past a naive
    # parser (browsers strip them, so the page and our parser must agree).
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate)

    if len(candidate) > MAX_URL_LENGTH:
        raise UrlNormalisationError(f"URL exceeds {MAX_URL_LENGTH} characters")

    # urlsplit() itself rejects some malformed netlocs — a bracketed component
    # that is not a valid IPv6 literal, "https://[::1]@metadata.goog/" being
    # the found-by-probing example — and it raises bare ValueError doing so.
    # This function's contract is that the only thing it ever raises is
    # UrlNormalisationError: hostile pages feed the frontier arbitrary hrefs
    # (fixture site 09), and an unexpected exception type is a crawler crash,
    # not a rejection.
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise UrlNormalisationError(f"unparseable URL: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlNormalisationError(
            f"scheme {scheme!r} is not permitted; only {sorted(ALLOWED_SCHEMES)} are"
        )

    # Reject userinfo outright. "https://evil.com@internal/" is a classic SSRF
    # and phishing primitive; there is no legitimate crawl target that needs
    # it, so refusing is strictly safer than normalising it away.
    if parts.username is not None or parts.password is not None:
        raise UrlNormalisationError("userinfo in URL is not permitted")

    try:
        raw_host = parts.hostname or ""
    except ValueError as exc:  # malformed IPv6 literal etc.
        raise UrlNormalisationError(f"unparseable host: {exc}") from exc
    host = _normalise_host(raw_host)

    try:
        port = parts.port
    except ValueError as exc:
        raise UrlNormalisationError(f"invalid port: {exc}") from exc

    # Rebuild the netloc, preserving bracketed literals. parts.hostname strips
    # "[" and "]", but a bare IPv6 host cannot round-trip: "https://::1/"
    # re-parses as an empty host plus a bogus port, breaking both idempotence
    # and the §10 identity contract. A DNS name never contains ":" (idna
    # rejects it), so a host that does — or that arrived bracketed, which also
    # covers IPvFuture spellings — is a literal and must be re-bracketed.
    was_bracketed = parts.netloc.startswith("[")
    netloc = f"[{host}]" if was_bracketed or ":" in host else host
    if port is not None and port != DEFAULT_PORTS[scheme]:
        if not 1 <= port <= MAX_PORT:
            raise UrlNormalisationError(f"port {port} out of range")
        netloc = f"{netloc}:{port}"

    path = parts.path or "/"
    path = _normalise_percent_encoding(path, safe="/")
    path = _resolve_dot_segments(path)
    if not path:
        path = "/"

    query = _normalise_query(parts.query, strip_tracking=strip_tracking)

    # Fragment removed unconditionally (§10 step 7). It is never sent to the
    # server, so two URLs differing only by fragment are one resource.
    return urlunsplit((scheme, netloc, path, query, ""))


def url_hash(url: str, *, strip_tracking: bool = True) -> str:
    """sha256 hex digest of the normalised URL.

    ARCHITECTURE §8: "``urls.url_hash`` = sha256 of the normalised URL, unique
    per site." Callers must not hash the raw input — that is the whole point.
    """
    return hashlib.sha256(normalise(url, strip_tracking=strip_tracking).encode("utf-8")).hexdigest()


def is_same_registrable_site(a: str, b: str) -> bool:
    """Compare hosts exactly after normalisation.

    Named "registrable site" but deliberately implemented as exact host
    equality: correct eTLD+1 evaluation needs the Public Suffix List, which is
    a data dependency with an update cadence. Until that list is vendored and
    version-pinned, an exact-host comparison is the honest conservative
    behaviour, and callers that need eTLD+1 must say so explicitly rather than
    silently getting a wrong answer for ``foo.co.uk``.
    """
    return urlsplit(normalise(a)).hostname == urlsplit(normalise(b)).hostname
