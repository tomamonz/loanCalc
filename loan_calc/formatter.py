"""Output helpers for the loan calculator.

This module provides simple functions to render amortization schedules and
summaries in a tabular text format. We rely only on built‑in printing and
string formatting to avoid external dependencies. If the environment has
``click``, its coloring utilities can enhance the output, but that is not
required.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple
from decimal import Decimal

from .data_models import ScheduleEntry


def print_summary(summary: Dict[str, object]) -> None:
    """Print a summary of loan metrics in a human‑readable format."""
    print("Summary")
    print("-" * 72)
    print(f"Principal financed : {summary['principal_financed']:.2f}")
    print(f"Total interest     : {summary['total_interest']:.2f}")
    if summary.get('total_overpayment', 0):
        print(f"Total overpayment  : {summary['total_overpayment']:.2f}")
    print(f"Total cost         : {summary['total_cost']:.2f}")
    print(f"APR (approx)       : {summary['apr'] * 100:.2f}%")
    print(f"Original end date  : {summary['original_end_date']}")
    print(f"New end date       : {summary['new_end_date']}")
    print(f"Payments made      : {summary['payments_made']}")
    # Show the highest (maximum) payment value for the schedule. This helps identify the
    # peak monthly cash outflow. For annuity loans this equals the constant installment; for
    # decreasing loans this corresponds to the first payment (before overpayments).
    if summary.get('max_payment'):
        print(f"Highest payment    : {summary['max_payment']:.2f}")
    comparison = summary.get('comparison')
    if comparison:
        print(f"Baseline interest  : {comparison['baseline_total_interest']:.2f}")
        print(f"Interest saved     : {comparison['interest_saved']:.2f}")
        print(f"Total cost saved   : {comparison['total_cost_saved']:.2f}")
        if comparison.get('months_saved'):
            print(f"Term reduction     : {int(comparison['months_saved'])} months")
    print("-" * 72)


def print_schedule(schedule: Iterable[ScheduleEntry], show_tranche: bool = False) -> None:
    """Print the amortization schedule as a simple table.

    Parameters
    ----------
    schedule: Iterable[ScheduleEntry]
        The schedule entries to print.
    show_tranche: bool
        Whether to include the ``Tranche_Disbursed`` column. By default,
        tranches are hidden because they are rarely used in standard schedules.
    """
    headers = [
        "Period",
        "Date",
        "StartBal",
        "Payment",
        "Principal",
        "Interest",
        "Overpay",
        "EndBal",
    ]
    if show_tranche:
        headers.append("Tranche")
    headers.append("Holiday")
    print("\t".join(headers))
    for entry in schedule:
        # Skip redundant zero rows (no payment, no interest, no overpayment, balance unchanged)
        from decimal import Decimal
        if (
            entry.payment == Decimal('0')
            and entry.principal_payment == Decimal('0')
            and entry.interest_payment == Decimal('0')
            and entry.overpayment == Decimal('0')
            and entry.starting_balance == Decimal('0')
            and entry.ending_balance == Decimal('0')
        ):
            continue
        row = [
            str(entry.period),
            entry.date.strftime("%Y-%m"),
            f"{entry.starting_balance:.2f}",
            f"{entry.payment:.2f}",
            f"{entry.principal_payment:.2f}",
            f"{entry.interest_payment:.2f}",
            f"{entry.overpayment:.2f}",
            f"{entry.ending_balance:.2f}",
        ]
        if show_tranche:
            row.append(f"{entry.tranche_disbursed:.2f}")
        row.append("Yes" if entry.holiday else "No")
        print("\t".join(row))


def print_comparison(s1: Dict[str, object], s2: Dict[str, object]) -> None:
    """Print a comparison of two loan summaries side by side.

    This function highlights which scenario is better in each metric by showing
    the difference (scenario2 - scenario1). A negative difference means the
    second scenario is cheaper or shorter.
    """
    print("Comparison")
    print("=" * 72)
    keys = [
        "total_cost",
        "total_interest",
        "payments_made",
    ]
    print(f"{'Metric':20s} {'Scenario1':>15s} {'Scenario2':>15s} {'Difference':>15s}")
    for key in keys:
        v1 = s1.get(key)
        v2 = s2.get(key)
        diff = v2 - v1
        print(f"{key:20s} {v1:15.2f} {v2:15.2f} {diff:15.2f}")
    print("=" * 72)