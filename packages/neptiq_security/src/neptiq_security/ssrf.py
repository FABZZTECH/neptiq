"""SSRF and DNS-rebinding defence.

ARCHITECTURE §14:

    "all egress through the proxy, which resolves DNS itself, validates every
     resolved address (IPv4 and IPv6 private, loopback, link-local, CGNAT,
     multicast, reserved, cloud metadata) and pins the validated IP for the
     connection, re-validating each redirect hop. CI corpus covers
     decimal/octal/hex encodings, IPv6-mapped IPv4, userinfo tricks, and
     redirect-to-internal chains."

The critical design point is the pinning. Validating a hostname and then
handing that hostname to a socket call is the DNS-rebinding bug: the attacker's
resolver returns a public address for our check and 169.254.169.254 for the
connect. So ``validate_destination`` returns the *validated IP*, and the caller
is required to connect to that IP with the original Host header. There is no
API here that validates a name without returning the address to use.

This module is pure with respect to the network: DNS resolution is injected as
a callable. That is what makes the adversarial corpus runnable as a fast unit
test with no network and no Docker, which matters because this is the code we
least want to leave untested.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from neptiq_core.errors import SsrfBlockedError

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Networks that must never be reachable from Zone U. Assembled explicitly
# rather than relying on ``is_private``, because ``is_private`` misses
# cloud-metadata (169.254.169.254 is link-local, which it does catch) but also
# because being explicit lets each entry carry the reason it is here.
_BLOCKED_V4: Final[tuple[tuple[str, str], ...]] = (
    ("0.0.0.0/8", "this-network / unspecified"),
    ("10.0.0.0/8", "RFC1918 private"),
    ("100.64.0.0/10", "CGNAT — RFC6598, routable inside carrier networks"),
    ("127.0.0.0/8", "loopback"),
    ("169.254.0.0/16", "link-local, includes 169.254.169.254 cloud metadata"),
    ("172.16.0.0/12", "RFC1918 private"),
    ("192.0.0.0/24", "IETF protocol assignments"),
    ("192.0.2.0/24", "TEST-NET-1"),
    ("192.31.196.0/24", "AS112"),
    ("192.52.193.0/24", "AMT"),
    ("192.88.99.0/24", "6to4 relay anycast (deprecated)"),
    ("192.168.0.0/16", "RFC1918 private"),
    ("192.175.48.0/24", "direct delegation AS112"),
    ("198.18.0.0/15", "benchmarking"),
    ("198.51.100.0/24", "TEST-NET-2"),
    ("203.0.113.0/24", "TEST-NET-3"),
    ("224.0.0.0/4", "multicast"),
    ("240.0.0.0/4", "reserved"),
    ("255.255.255.255/32", "broadcast"),
)

_BLOCKED_V6: Final[tuple[tuple[str, str], ...]] = (
    ("::/128", "unspecified"),
    ("::1/128", "loopback"),
    ("::ffff:0:0/96", "IPv4-mapped — must be validated as its IPv4 form"),
    ("::/96", "IPv4-compatible (deprecated)"),
    ("64:ff9b::/96", "NAT64 — can reach RFC1918 via translation"),
    ("100::/64", "discard-only"),
    ("2001::/32", "Teredo"),
    ("2001:10::/28", "ORCHID (deprecated)"),
    ("2001:20::/28", "ORCHIDv2"),
    ("2001:db8::/32", "documentation"),
    ("2002::/16", "6to4"),
    ("fc00::/7", "unique local address"),
    ("fe80::/10", "link-local"),
    ("ff00::/8", "multicast"),
)

BLOCKED_NETWORKS: Final[tuple[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, str], ...]] = (
    tuple((ipaddress.ip_network(c), r) for c, r in _BLOCKED_V4)
    + tuple((ipaddress.ip_network(c), r) for c, r in _BLOCKED_V6)
)

# Cloud metadata endpoints called out explicitly so the block reason is
# unambiguous in logs, even though the ranges above already cover them.
CLOUD_METADATA_HOSTS: Final = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure / DigitalOcean / OpenStack
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud
        "fd00:ec2::254",  # AWS IMDSv2 over IPv6
    }
)

# A bare integer, or hex, or octal-looking host. Browsers and libc's inet_aton
# accept all of these as IPv4: http://2130706433/ is 127.0.0.1, and
# http://0177.0.0.1/ is also 127.0.0.1. Any validator that only looks for
# dotted-quad text misses them entirely, which is the single most common SSRF
# bypass in the wild.
_ALL_DIGITS: Final = re.compile(r"^[0-9]+$")
_HEX_HOST: Final = re.compile(r"^0[xX][0-9a-fA-F]+$")
_MIXED_NUMERIC: Final = re.compile(r"^[0-9xXa-fA-F]+(\.[0-9xXa-fA-F]+)*$")

# inet_aton octet/field widths. Named because the asymmetry is the whole point:
# with fewer than four fields the LAST field absorbs all remaining low octets,
# which is why 127.1 and 2130706433 both mean 127.0.0.1.
_OCTET_MAX: Final = 0xFF
_TWO_OCTET_MAX: Final = 0xFFFF
_THREE_OCTET_MAX: Final = 0xFFFFFF
_IPV4_MAX: Final = 0xFFFFFFFF
_DOTTED_QUAD_FIELDS: Final = 4
_THREE_FIELDS: Final = 3
_TWO_FIELDS: Final = 2

DnsResolver = Callable[[str], Sequence[str]]


@dataclass(frozen=True, slots=True)
class ValidatedDestination:
    """The result of a successful validation.

    ``ip`` is what the caller MUST connect to. ``host`` is what the caller MUST
    send as the Host header / SNI. Splitting them is the entire anti-rebinding
    mechanism; a caller that reconnects by name has reintroduced the bug.
    """

    host: str
    ip: IpAddress
    port: int
    scheme: str

    @property
    def connect_target(self) -> str:
        if isinstance(self.ip, ipaddress.IPv6Address):
            return f"[{self.ip}]:{self.port}"
        return f"{self.ip}:{self.port}"


def _canonicalise_numeric_host(host: str) -> str | None:  # noqa: PLR0911, PLR0912
    """Convert obfuscated numeric IPv4 spellings to dotted-quad.

    PLR0911/PLR0912 (many returns and branches) are accepted deliberately.
    Each branch is one documented SSRF bypass encoding, and each early return
    is "this is not that encoding". Refactoring into a table of handlers would
    hide which encodings are covered, and coverage is the security property
    being asserted here. The numeric encodings below are enumerated in
    tests/unit/test_ssrf.py; the full adversarial corpus — a >=60-URL set
    with real-DNS private-range names, redirect chains and cloud-metadata
    endpoints — lives in tests/security/test_ssrf_corpus.py (Task 2B, ADR
    0001 entry 9).

    Handles:
      * decimal   2130706433        -> 127.0.0.1
      * hex       0x7f000001        -> 127.0.0.1
      * octal     0177.0.0.01       -> 127.0.0.1
      * mixed     127.0x0.0.1       -> 127.0.0.1
      * short     127.1             -> 127.0.0.1

    Returns None if the host is not a numeric IPv4 spelling at all.
    """
    if _ALL_DIGITS.match(host):
        try:
            value = int(host, 10)
        except ValueError:
            return None
        if 0 <= value <= _IPV4_MAX:
            return str(ipaddress.IPv4Address(value))
        return None

    if _HEX_HOST.match(host):
        try:
            value = int(host, 16)
        except ValueError:
            return None
        if 0 <= value <= _IPV4_MAX:
            return str(ipaddress.IPv4Address(value))
        return None

    if not _MIXED_NUMERIC.match(host):
        return None

    parts = host.split(".")
    if not 1 <= len(parts) <= _DOTTED_QUAD_FIELDS:
        return None

    values: list[int] = []
    for part in parts:
        if part == "":
            return None
        try:
            if part.lower().startswith("0x"):
                values.append(int(part, 16))
            elif part.startswith("0") and len(part) > 1:
                values.append(int(part, 8))  # octal, e.g. 0177
            else:
                values.append(int(part, 10))
        except ValueError:
            return None

    # inet_aton semantics: the final part absorbs all remaining low octets.
    if len(values) == _DOTTED_QUAD_FIELDS:
        if any(v > _OCTET_MAX for v in values):
            return None
        packed = (values[0] << 24) | (values[1] << 16) | (values[2] << 8) | values[3]
    elif len(values) == _THREE_FIELDS:
        if values[0] > _OCTET_MAX or values[1] > _OCTET_MAX or values[2] > _TWO_OCTET_MAX:
            return None
        packed = (values[0] << 24) | (values[1] << 16) | values[2]
    elif len(values) == _TWO_FIELDS:
        if values[0] > _OCTET_MAX or values[1] > _THREE_OCTET_MAX:
            return None
        packed = (values[0] << 24) | values[1]
    else:
        if values[0] > _IPV4_MAX:
            return None
        packed = values[0]

    return str(ipaddress.IPv4Address(packed))


def classify_ip(ip: IpAddress) -> str | None:
    """Return the block reason for ``ip``, or None if it is permitted.

    IPv4-mapped and 6to4/Teredo-embedded IPv6 addresses are unwrapped and
    re-checked as IPv4, because ::ffff:127.0.0.1 reaches loopback while looking
    like an ordinary IPv6 address to a naive range check.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            inner = classify_ip(ip.ipv4_mapped)
            return inner if inner else None
        if ip.sixtofour is not None:
            inner = classify_ip(ip.sixtofour)
            if inner:
                return f"6to4-embedded {inner}"
        if ip.teredo is not None:
            server, client = ip.teredo
            for embedded in (server, client):
                inner = classify_ip(embedded)
                if inner:
                    return f"Teredo-embedded {inner}"

    for network, reason in BLOCKED_NETWORKS:
        if ip.version == network.version and ip in network:
            return reason

    # Backstop: anything the stdlib considers non-global that we have not
    # already named. Keeps us safe against future allocations.
    if not ip.is_global:
        return "non-global address"
    return None


def validate_destination(  # noqa: PLR0912
    *,
    scheme: str,
    host: str,
    port: int,
    resolver: DnsResolver,
) -> ValidatedDestination:
    """Resolve ``host`` and return a pinned, validated destination.

    PLR0912 accepted: the branch count is the ordered sequence of checks
    (metadata host, bracketed literal, numeric obfuscation, literal address,
    DNS resolution, per-answer validation). Order is load-bearing, so it is
    written as a linear sequence rather than dispatched.

    Raises ``SsrfBlockedError`` if any resolved address is disallowed. Note
    "any", not "the first": a hostname resolving to one public and one private
    address is a rebinding attack, so the whole destination is refused rather
    than cherry-picking a permitted answer.
    """
    if scheme not in ("http", "https"):
        raise SsrfBlockedError(f"scheme {scheme!r} is not permitted")

    normalised = host.strip().rstrip(".").lower()
    if not normalised:
        raise SsrfBlockedError("empty host")

    if normalised in CLOUD_METADATA_HOSTS:
        raise SsrfBlockedError("destination is a known cloud metadata endpoint")

    # Bracketed IPv6 literal.
    if normalised.startswith("[") and normalised.endswith("]"):
        normalised = normalised[1:-1]

    # 1. Obfuscated numeric IPv4 spellings.
    canonical = _canonicalise_numeric_host(normalised)
    if canonical is not None:
        normalised = canonical

    # 2. Literal address: no DNS needed, validate directly.
    try:
        literal = ipaddress.ip_address(normalised)
    except ValueError:
        literal = None

    if literal is not None:
        reason = classify_ip(literal)
        if reason:
            raise SsrfBlockedError(f"destination address is not permitted ({reason})")
        return ValidatedDestination(host=host, ip=literal, port=port, scheme=scheme)

    # 3. Hostname: resolve ourselves, validate EVERY answer, pin the first.
    try:
        answers = list(resolver(normalised))
    except Exception as exc:
        raise SsrfBlockedError(f"could not resolve destination host: {exc}") from exc

    if not answers:
        raise SsrfBlockedError("destination host did not resolve")

    parsed: list[IpAddress] = []
    for answer in answers:
        try:
            parsed.append(ipaddress.ip_address(answer))
        except ValueError as exc:
            raise SsrfBlockedError(f"resolver returned an unparseable address: {exc}") from exc

    for ip in parsed:
        reason = classify_ip(ip)
        if reason:
            # Deliberately does not echo the address: that would confirm
            # internal topology to whoever supplied the hostname.
            raise SsrfBlockedError(f"destination host resolves to a disallowed address ({reason})")

    return ValidatedDestination(host=normalised, ip=parsed[0], port=port, scheme=scheme)


def validate_redirect_hop(
    *,
    scheme: str,
    host: str,
    port: int,
    resolver: DnsResolver,
    hop_index: int,
    max_hops: int = 5,
) -> ValidatedDestination:
    """Validate one redirect hop.

    ARCHITECTURE §10 caps the chain at 5 "with each hop re-validated for SSRF".
    A redirect to an internal address is the bypass that defeats validating
    only the initial URL, so this is a separate named function to make its
    presence in the fetch loop obvious in review.
    """
    if hop_index > max_hops:
        raise SsrfBlockedError(f"redirect chain exceeded {max_hops} hops")
    return validate_destination(scheme=scheme, host=host, port=port, resolver=resolver)


__all__ = [
    "BLOCKED_NETWORKS",
    "CLOUD_METADATA_HOSTS",
    "DnsResolver",
    "ValidatedDestination",
    "classify_ip",
    "validate_destination",
    "validate_redirect_hop",
]
