"""URL normalisation: unit + Hypothesis property tests.

ARCHITECTURE §10 states one hard requirement: normalisation "must be injective
on the fixture corpus — a collision silently corrupts both the frontier and the
evidence ledger". These tests are the enforcement.
"""

from __future__ import annotations

import contextlib
from urllib.parse import urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from neptiq_url import UrlNormalisationError, normalise, url_hash


class TestTransformList:
    """One test per transform in the §10 list, in order."""

    def test_lowercases_scheme_and_host(self) -> None:
        assert normalise("HTTP://EXAMPLE.COM/Path") == "http://example.com/Path"

    def test_preserves_path_case(self) -> None:
        # Paths ARE case-sensitive at almost every origin. Lowercasing the path
        # would merge two distinct resources into one hash.
        assert normalise("https://e.com/A") != normalise("https://e.com/a")

    def test_idn_to_punycode(self) -> None:
        assert normalise("https://bücher.example/") == "https://xn--bcher-kva.example/"

    def test_removes_default_ports(self) -> None:
        assert normalise("https://e.com:443/") == "https://e.com/"
        assert normalise("http://e.com:80/") == "http://e.com/"

    def test_keeps_non_default_port(self) -> None:
        assert normalise("https://e.com:8443/") == "https://e.com:8443/"

    def test_resolves_dot_segments(self) -> None:
        assert normalise("https://e.com/a/b/../c") == "https://e.com/a/c"
        assert normalise("https://e.com/./a") == "https://e.com/a"

    def test_preserves_trailing_slash(self) -> None:
        # /a/ and /a are genuinely different resources; one redirecting to the
        # other is itself a finding we must be able to detect.
        assert normalise("https://e.com/a/") != normalise("https://e.com/a")

    def test_percent_encoding_uppercased(self) -> None:
        assert normalise("https://e.com/a%2fb") == "https://e.com/a%2Fb"

    def test_unreserved_percent_decoded(self) -> None:
        # %7E and ~ denote the same resource; leaving both spellings alive
        # would admit the same URL to the frontier twice.
        assert normalise("https://e.com/%7Euser") == "https://e.com/~user"

    def test_strips_tracking_params(self) -> None:
        assert normalise("https://e.com/p?utm_source=x&id=7") == "https://e.com/p?id=7"

    def test_removes_fragment(self) -> None:
        assert normalise("https://e.com/p#section") == "https://e.com/p"

    def test_strips_trailing_dot_host(self) -> None:
        assert normalise("https://e.com./") == "https://e.com/"


class TestQueryOrderPreserved:
    """Order preservation is a CORRECTNESS requirement, not a style choice."""

    def test_order_is_not_sorted(self) -> None:
        # Sorting would map ?a=1&b=2 and ?b=2&a=1 onto one hash. For ordered
        # filters and signed URLs those are different resources at the origin,
        # so sorting is exactly the collision §10 forbids.
        assert normalise("https://e.com/?b=2&a=1") == "https://e.com/?b=2&a=1"
        assert url_hash("https://e.com/?a=1&b=2") != url_hash("https://e.com/?b=2&a=1")

    def test_valueless_and_empty_value_distinguished(self) -> None:
        assert normalise("https://e.com/?a") != normalise("https://e.com/?a=")


class TestRejections:
    @pytest.mark.parametrize(
        "bad",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "",
            "   ",
            "not-a-url",
            "https://user:pw@internal/",  # userinfo: SSRF/phishing primitive
            "https:///nohost",
        ],
    )
    def test_rejects(self, bad: str) -> None:
        with pytest.raises(UrlNormalisationError):
            normalise(bad)

    def test_strips_embedded_control_characters(self) -> None:
        # Browsers strip tab/newline inside URLs. Our parser must agree, or a
        # hostile page can point us somewhere the browser would not go.
        assert normalise("https://e.com/\tpath\n") == "https://e.com/path"


class TestParseBoundaryRegression:
    """Regression (Task 2B-1, defect 1): raw ValueError escaped the boundary.

    ``urlsplit()`` raises a BARE ``ValueError`` for a bracketed netloc that is
    not a valid IPv6 literal. ``normalise()``'s contract — the reason
    ``test_never_crashes_on_arbitrary_text`` exists — is that the only thing
    it ever raises is ``UrlNormalisationError``. These exact inputs crashed
    with the raw stdlib exception before the fix.
    """

    @pytest.mark.parametrize(
        "bad",
        [
            "https://[::1]@metadata.goog/",  # the found-by-probing input
            "https://[evil.com]/",  # same escape route: DNS name inside brackets
        ],
    )
    def test_malformed_bracketed_netloc_raises_urlnormalisationerror(self, bad: str) -> None:
        # A bare ValueError is NOT an instance of UrlNormalisationError, so
        # this raises-assertion fails on the pre-fix behaviour. That is the
        # regression this test pins: rejection, never an unexpected crash.
        with pytest.raises(UrlNormalisationError):
            normalise(bad)


class TestIpv6LiteralBracketPreservation:
    """Regression (Task 2B-1, defect 2): bracketed IPv6 hosts lost their brackets.

    ``parts.hostname`` strips ``[`` and ``]``, and the netloc rebuild never put
    them back, so ``normalise("https://[::1]/")`` returned ``https://::1/`` —
    a string no standard parser can re-read (empty host, bogus port). That
    broke idempotence, the re-parse round-trip, and therefore the §10 identity
    contract on every IPv6 target.
    """

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://[::1]/", "https://[::1]/"),
            (
                "https://[2606:2800:220:1:248:1893:25c8:1946]/",
                "https://[2606:2800:220:1:248:1893:25c8:1946]/",
            ),
            ("http://[fe80::1]:8080/x", "http://[fe80::1]:8080/x"),
            ("https://[::1]:443/x", "https://[::1]/x"),  # default port still stripped
        ],
    )
    def test_brackets_preserved(self, url: str, expected: str) -> None:
        assert normalise(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://[::1]/",
            "https://[2606:2800:220:1:248:1893:25c8:1946]/",
            "http://[fe80::1]:8080/x",
        ],
    )
    def test_output_re_parses_to_the_same_host(self, url: str) -> None:
        # The §10 contract is about the OUTPUT: it must be a URL whose host
        # survives a re-parse by a standard parser. The pre-fix output did not.
        once = normalise(url)
        assert urlsplit(once).hostname == urlsplit(url).hostname

    @pytest.mark.parametrize(
        "url",
        [
            "https://[::1]/",
            "https://[2606:2800:220:1:248:1893:25c8:1946]/",
            "http://[fe80::1]:8080/x",
        ],
    )
    def test_idempotent_on_ipv6_output(self, url: str) -> None:
        # The general idempotence property test cannot reach these inputs
        # (_SAFE_URLS generates DNS hosts only), so they are pinned here.
        once = normalise(url)
        assert normalise(once) == once

    def test_distinct_ipv6_hosts_hash_differently(self) -> None:
        # Injectivity (§10) must hold in IPv6 space too, now that the output
        # round-trips. Before the fix, url_hash() happily hashed an unparseable
        # string — the hash looked fine, which is how the defect hid.
        assert url_hash("https://[::1]/") != url_hash("https://[fe80::1]/")


_SAFE_URLS = st.builds(
    lambda host, path, query: f"https://{host}.example/{path}" + (f"?{query}" if query else ""),
    host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12),
    path=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJ0123456789-_/", max_size=40),
    query=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789=&", max_size=30),
)


@pytest.mark.property
class TestProperties:
    @settings(max_examples=400, deadline=None)
    @given(_SAFE_URLS)
    def test_idempotent(self, url: str) -> None:
        """normalise(normalise(u)) == normalise(u).

        A non-idempotent normaliser makes a URL's hash depend on how many times
        it has passed through the pipeline — a corruption bug waiting for a
        retry to trigger it.
        """
        once = normalise(url)
        assert normalise(once) == once

    @settings(max_examples=400, deadline=None)
    @given(_SAFE_URLS)
    def test_output_is_absolute_and_fragmentless(self, url: str) -> None:
        out = normalise(url)
        assert out.startswith("https://")
        assert "#" not in out

    @settings(max_examples=300, deadline=None)
    @given(_SAFE_URLS)
    def test_hash_matches_normalised_form(self, url: str) -> None:
        import hashlib

        expected = hashlib.sha256(normalise(url).encode()).hexdigest()
        assert url_hash(url) == expected

    @settings(max_examples=300, deadline=None)
    @given(_SAFE_URLS, _SAFE_URLS)
    def test_injective_distinct_inputs_distinct_hashes(self, a: str, b: str) -> None:
        """INJECTIVITY — the §10 requirement.

        If two URLs normalise to different strings they must hash differently,
        and if they normalise to the same string they must hash identically.
        """
        na, nb = normalise(a), normalise(b)
        if na == nb:
            assert url_hash(a) == url_hash(b)
        else:
            assert url_hash(a) != url_hash(b)

    @settings(max_examples=200, deadline=None)
    @given(st.text(max_size=100))
    def test_never_crashes_on_arbitrary_text(self, text: str) -> None:
        """Only ever UrlNormalisationError — never an unexpected exception.

        Frontier input includes hrefs from hostile pages (fixture site 09), so
        an unhandled TypeError here is a crawler crash.
        """
        with contextlib.suppress(UrlNormalisationError):
            normalise(text)
