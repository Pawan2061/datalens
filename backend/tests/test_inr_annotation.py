"""Tests for the deterministic INR unit annotation in app/agent/graph.py.

Regression guard for the synthesis 10x unit error: the LLM divided
8-9 digit rupee values itself and miscounted digits (₹10.20 Cr was
reported as ₹1.02 Cr, ₹8.98 Cr as ₹89.80 L). Large numbers in the
synthesis payload now carry their exact Cr/L conversion computed in
Python; these tests pin that math.
"""
from __future__ import annotations

from app.agent.graph import _annotate_numeric, _format_inr_units, _indian_commas


class TestFormatInrUnits:
    def test_crore_values_from_failing_screenshots(self):
        assert _format_inr_units(102005098.13) == "10.20 Cr"
        assert _format_inr_units(89802574.33) == "8.98 Cr"
        assert _format_inr_units(34326630.72) == "3.43 Cr"

    def test_lakh_values(self):
        assert _format_inr_units(364627.88) == "3.65 L"
        assert _format_inr_units(2641379) == "26.41 L"

    def test_boundaries(self):
        assert _format_inr_units(1e7) == "1.00 Cr"
        assert _format_inr_units(1e5) == "1.00 L"
        assert _format_inr_units(99999.99) is None
        assert _format_inr_units(12500) is None

    def test_negative(self):
        assert _format_inr_units(-89802574.33) == "-8.98 Cr"


class TestIndianCommas:
    def test_grouping(self):
        assert _indian_commas(102005098.13) == "10,20,05,098.13"
        assert _indian_commas(364627.88) == "3,64,627.88"
        assert _indian_commas(886902) == "8,86,902.00"
        assert _indian_commas(998) == "998.00"

    def test_negative(self):
        assert _indian_commas(-102005098.13) == "-10,20,05,098.13"


class TestAnnotateNumeric:
    def test_large_values_get_annotation(self):
        assert _annotate_numeric(102005098.13) == "10,20,05,098.13 (= 10.20 Cr)"
        assert _annotate_numeric(89802574.33) == "8,98,02,574.33 (= 8.98 Cr)"
        assert _annotate_numeric(364627.88) == "3,64,627.88 (= 3.65 L)"

    def test_small_values_pass_through_unchanged(self):
        # Invoice counts, piece lengths (PIECE_DISPVAL) etc. must stay numeric
        # so comparisons like MAX(PIECE_DISPVAL) >= N keep working.
        assert _annotate_numeric(10438) == 10438
        assert _annotate_numeric(96.7) == 96.7
        assert _annotate_numeric(0) == 0

    def test_non_numerics_pass_through(self):
        assert _annotate_numeric("CUBANA") == "CUBANA"
        assert _annotate_numeric(None) is None
        assert _annotate_numeric(True) is True
