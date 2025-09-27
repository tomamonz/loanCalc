"""Utility functions for the loan calculator.

This module provides helpers for parsing user input into Python data types and
for handling dates, including adding months and normalizing year-month strings
to ``datetime.date`` instances. It uses Python's ``datetime`` module to
calculate month offsets.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext
import calendar
from typing import Optional

getcontext().prec = 28  # increase decimal precision to avoid rounding errors


def parse_year_month(ym: str) -> date:
    """Parse a YYYY-MM string into a ``date`` object (first day of month).

    Parameters
    ----------
    ym: str
        A string in the form ``"YYYY-MM"``. The day component, if present,
        will be ignored.

    Returns
    -------
    date
        A date object representing the first day of the specified month.

    Raises
    ------
    ValueError
        If the string is not a valid year-month.
    """
    try:
        parts = ym.split("-")
        if len(parts) < 2:
            raise ValueError
        year = int(parts[0])
        month = int(parts[1])
        return date(year, month, 1)
    except Exception as exc:
        raise ValueError(f"Invalid year-month string: {ym}") from exc


def add_months(dt: date, months: int) -> date:
    """Return a new date a number of months after ``dt``.

    The day of the month is clamped to the last valid day if needed (e.g.,
    adding one month to Jan 31 yields Feb 28 or 29).
    """
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def decimal_from_str(value: str) -> Decimal:
    """Convert a numeric string into a ``Decimal``.

    The function strips any commas and handles both integer and float-like
    strings. It raises ``ValueError`` if conversion fails.
    """
    try:
        cleaned = value.replace(",", "")
        return Decimal(cleaned)
    except Exception as exc:
        raise ValueError(f"Invalid numeric value: {value}") from exc