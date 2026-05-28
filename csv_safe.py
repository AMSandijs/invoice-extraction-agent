"""Neutralize CSV / spreadsheet formula injection (CWE-1236).

Spreadsheet software (Excel, Google Sheets, LibreOffice) evaluates a cell whose
text begins with a formula trigger. Invoice fields are extracted from
user-supplied files, so a malicious value like ``=HYPERLINK(...)`` could run
when an exported CSV is opened. Prefixing such values with a single quote makes
the spreadsheet treat them as literal text.
"""

# Characters that start a formula (or a control char that can shift the cell).
_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "\n")


def sanitize_cell(value):
    """Return a CSV-safe cell value, neutralizing formula injection.

    Non-string scalars (ints, floats) pass through unchanged so legitimate
    numeric values — including negative amounts — stay numeric. ``None`` becomes
    an empty string. Strings that begin with a formula trigger are prefixed with
    a single quote.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value and value[0] in _TRIGGERS:
        return "'" + value
    return value
