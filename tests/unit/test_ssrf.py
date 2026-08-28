"""SSRF adversarial corpus (ARCHITECTURE §14).

Runs entirely in-process with an injected resolver, so the full bypass corpus is
verified in the authoring sandbox with no Docker and no network. This is the
code we least want untested.
"""

from __future__ import annotations

import ipaddress

import pytest

from neptiq_core.errors import SsrfBlockedError
from neptiq_security.ssrf import classify_ip, validate_destination


def _resolver(mapping: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"NXDOMAIN {host}")
        return mapping[host]

    return resolve


class TestObfuscatedIpv4:
    """§14: "CI corpus covers decimal/octal/hex encodings"."""

    @pytest.mark.parametrize(
        "host",
        [
            "127.0.0.1",
            "2130706433",
            "0x7f000001",
            "0177.0.0.1",
            "127.1",
            "127.0.1",
            "127.0x0.0.1",
            "0x7f.1",
            "169.254.169.254",
            "0xa9fea9fe",
            "2852039166",
            "10.0.0.1",
            "192.168.1.1",
            "172.16.0.1",
            "100.64.0.1",
            "0.0.0.0",  # noqa: S104 - an SSRF target, not a bind address
            "255.255.255.255",
            "224.0.0.1",
        ],
    )
    def test_blocked(self, host: str) -> None:
        with pytest.raises(SsrfBlockedError):
            validate_destination(scheme="https", host=host, port=443, resolver=_resolver({}))


class TestIpv6:
    @pytest.mark.parametrize(
        "host",
        [
            "::1",
            "::ffff:127.0.0.1",
            "::ffff:7f00:1",
            "fd00::1",
            "fe80::1",
            "::",
            "2002:7f00:0001::",
            "fd00:ec2::254",
            "64:ff9b::a00:1",
        ],
    )
    def test_blocked(self, host: str) -> None:
        with pytest.raises(SsrfBlockedError):
            validate_destination(scheme="https", host=host, port=443, resolver=_resolver({}))


class TestRebinding:
    def test_all_answers_validated_not_just_first(self) -> None:
        """A name resolving to one public AND one private address is refused.

        Cherry-picking the permitted answer is the DNS-rebinding bug.
        """
        with pytest.raises(SsrfBlockedError):
            validate_destination(
                scheme="https",
                host="evil.example",
                port=443,
                resolver=_resolver({"evil.example": ["93.184.216.34", "10.0.0.5"]}),
            )

    def test_returns_pinned_ip_for_caller_to_connect_to(self) -> None:
        """The API cannot validate a name without returning the address."""
        dest = validate_destination(
            scheme="https",
            host="ok.example",
            port=443,
            resolver=_resolver({"ok.example": ["93.184.216.34"]}),
        )
        assert dest.ip == ipaddress.ip_address("93.184.216.34")
        assert dest.connect_target == "93.184.216.34:443"

    def test_nxdomain_is_a_block_not_a_crash(self) -> None:
        with pytest.raises(SsrfBlockedError):
            validate_destination(
                scheme="https", host="nope.example", port=443, resolver=_resolver({})
            )


class TestMetadataAndSchemes:
    @pytest.mark.parametrize(
        "host", ["metadata.google.internal", "169.254.169.254", "100.100.100.200"]
    )
    def test_cloud_metadata_blocked(self, host: str) -> None:
        with pytest.raises(SsrfBlockedError):
            validate_destination(scheme="http", host=host, port=80, resolver=_resolver({}))

    @pytest.mark.parametrize("scheme", ["file", "gopher", "ftp", "dict", "ldap"])
    def test_non_http_schemes_blocked(self, scheme: str) -> None:
        with pytest.raises(SsrfBlockedError):
            validate_destination(scheme=scheme, host="e.com", port=80, resolver=_resolver({}))


class TestPermitted:
    def test_public_address_allowed(self) -> None:
        assert classify_ip(ipaddress.ip_address("93.184.216.34")) is None

    def test_public_ipv6_allowed(self) -> None:
        assert classify_ip(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946")) is None
