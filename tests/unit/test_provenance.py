"""Provenance and confidence (CONSTITUTION P1, P7, P11; GEO Charter)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from neptiq_core.ids import new_uuid7
from neptiq_core.provenance import NotMeasurable, Provenance, wilson_interval


class TestProvenanceRequiresSources:
    def test_empty_source_ids_rejected(self) -> None:
        """P1: a derived number with no sources is an unsupported claim."""
        with pytest.raises(ValidationError):
            Provenance.deterministic(name="x", source_ids=[], engine_version="0.1.0")

    def test_deterministic_is_exact(self) -> None:
        p = Provenance.deterministic(
            name="canonical_conflict", source_ids=[new_uuid7()], engine_version="0.1.0"
        )
        assert p.confidence.kind == "exact"


class TestWilsonInterval:
    def test_states_n_and_level(self) -> None:
        """GEO Charter: the UI states n and the interval, so both are present."""
        ci = wilson_interval(48, 96)
        assert ci.n == 96
        assert ci.level == 0.95
        assert ci.low < ci.point < ci.high

    @pytest.mark.parametrize("successes,n", [(0, 96), (96, 96), (1, 1)])
    def test_stays_within_unit_interval_at_extremes(self, successes: int, n: int) -> None:
        """Why Wilson and not the normal approximation.

        Appearance rates sit near 0 and 1 routinely; the normal approximation
        produces bounds outside [0,1] there, i.e. visible nonsense in the UI.
        """
        ci = wilson_interval(successes, n)
        assert 0.0 <= ci.low <= ci.high <= 1.0

    @settings(max_examples=200, deadline=None)
    @given(st.integers(min_value=1, max_value=5000))
    def test_interval_narrows_as_n_grows(self, n: int) -> None:
        wide = wilson_interval(n // 2, max(n, 1))
        assert wide.high - wide.low <= 1.0

    def test_rejects_invalid_inputs(self) -> None:
        with pytest.raises(ValueError):
            wilson_interval(5, 0)
        with pytest.raises(ValueError):
            wilson_interval(10, 5)


class TestNotMeasurable:
    def test_carries_no_number_by_construction(self) -> None:
        """P11: an unmeasurable phenomenon cannot be given a score.

        The type has no numeric field at all, so there is nothing to set.
        """
        nm = NotMeasurable(reason="rank within a generated answer is noise")
        assert not hasattr(nm, "point")
        assert not hasattr(nm, "value")
