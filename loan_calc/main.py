"""Command‑line interface for the loan calculator.

This module uses the ``click`` library (which is available in the runtime
environment) to implement a multi‑command interface. Users can compute full
amortization schedules, view summaries or compare two loan scenarios. Results
can be printed to the terminal or exported to JSON/CSV files.
"""

from __future__ import annotations

import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import click

from .data_models import LoanConfig, Overpayment, Tranche
from .utils import parse_year_month, decimal_from_str, add_months
from .engine import compute_schedule
from .formatter import print_schedule, print_summary, print_comparison


def parse_amount(value: str) -> float:
    """Parse a numeric string with optional suffixes.

    Accepts plain floats ("500000") and shorthand with ``k``/``m`` suffixes
    (e.g., "500k" meaning 500_000). Returns a float.
    """
    value = value.strip().lower()
    value = value.replace(",", "")
    factor = 1.0
    if value.endswith("k"):
        factor = 1_000.0
        value = value[:-1]
    elif value.endswith("m"):
        factor = 1_000_000.0
        value = value[:-1]
    try:
        return float(value) * factor
    except ValueError:
        raise click.BadParameter(f"Invalid amount: {value}")


def parse_percent(value: str) -> float:
    """Parse a percentage string (e.g. "80" or "0.8")."""
    value = value.strip()
    if value.endswith("%"):
        value = value[:-1]
    try:
        p = float(value)
    except ValueError:
        raise click.BadParameter(f"Invalid percentage: {value}")
    # If the user enters a number like 80, treat it as 80%
    if p > 1:
        p = p / 100
    return p


def parse_overpayment_strings(values: Tuple[str, ...]) -> List[Overpayment]:
    overpayments: List[Overpayment] = []
    for item in values:
        parts = item.split(":")
        if len(parts) != 3:
            raise click.BadParameter(
                f"Overpayment must be in YYYY-MM:AMOUNT:TYPE format; got {item}"
            )
        ym, amt_str, typ = parts
        try:
            dt = parse_year_month(ym)
        except ValueError as exc:
            raise click.BadParameter(str(exc))
        amount = decimal_from_str(str(parse_amount(amt_str)))
        typ = typ.lower()
        if typ not in ("term", "installment"):
            raise click.BadParameter(
                f"Overpayment type must be 'term' or 'installment'; got {typ}"
            )
        overpayments.append(Overpayment(date=dt, amount=amount, type=typ))
    return overpayments


def parse_tranche_strings(values: Tuple[str, ...], principal: float) -> List[Tranche]:
    tranches: List[Tranche] = []
    for item in values:
        parts = item.split(":")
        if len(parts) != 2:
            raise click.BadParameter(
                f"Tranche must be in YYYY-MM:PERCENT format; got {item}"
            )
        ym, percent_str = parts
        try:
            dt = parse_year_month(ym)
        except ValueError as exc:
            raise click.BadParameter(str(exc))
        pct = parse_percent(percent_str)
        tranches.append(Tranche(date=dt, percent=decimal_from_str(str(pct))))
    return tranches


def parse_holiday_strings(values: Tuple[str, ...]) -> List[Any]:
    holidays = []
    for item in values:
        try:
            dt = parse_year_month(item)
        except ValueError as exc:
            raise click.BadParameter(str(exc))
        holidays.append(dt)
    return holidays


def build_config_from_options(
    principal: str,
    rate: float,
    term: int,
    loan_type: str,
    start_date: str,
    down_payment: Optional[str],
    tranche: Tuple[str, ...],
    overpayment: Tuple[str, ...],
    holiday: Tuple[str, ...],
    monthly_overpayment: Optional[str] = None,
    constant_payment: Optional[str] = None,
) -> LoanConfig:
    # Convert principal and down payment using parse_amount
    principal_value = decimal_from_str(str(parse_amount(principal)))
    down_payment_value = decimal_from_str(
        str(parse_amount(down_payment)) if down_payment else "0"
    )
    # Parse start date
    try:
        start_dt = parse_year_month(start_date)
    except ValueError as exc:
        raise click.BadParameter(str(exc))
    # Parse tranches and overpayments
    tranches = parse_tranche_strings(tranche, float(principal_value)) if tranche else []
    # parse explicit overpayment entries
    overpayments = parse_overpayment_strings(overpayment) if overpayment else []
    holidays = parse_holiday_strings(holiday) if holiday else []
    # Handle monthly overpayment: string of format AMOUNT:TYPE
    if monthly_overpayment:
        parts = monthly_overpayment.split(":")
        if len(parts) != 2:
            raise click.BadParameter(
                "Monthly overpayment must be in AMOUNT:TYPE format, e.g., '500:term'"
            )
        amt_str, typ = parts
        try:
            amount_float = parse_amount(amt_str)
        except Exception as exc:
            raise click.BadParameter(str(exc))
        if typ.lower() not in ("term", "installment"):
            raise click.BadParameter(
                "Monthly overpayment type must be 'term' or 'installment'"
            )
        # Create an overpayment entry for every month from start date through the term
        amount_dec = decimal_from_str(str(amount_float))
        for i in range(term):
            dt_i = add_months(start_dt, i)
            overpayments.append(
                Overpayment(date=dt_i, amount=amount_dec, type=typ.lower())
            )
    # Build config
    # Parse constant (target) payment if provided
    target_payment_value = None
    if constant_payment:
        # Parse numeric using parse_amount
        try:
            amount_float = parse_amount(constant_payment)
            target_payment_value = decimal_from_str(str(amount_float))
        except Exception as exc:
            raise click.BadParameter(str(exc))
    return LoanConfig(
        principal=principal_value,
        rate=decimal_from_str(str(rate)),
        term=term,
        start_date=start_dt,
        loan_type=loan_type.lower(),
        down_payment=down_payment_value,
        tranches=tranches,
        overpayments=overpayments,
        holidays=holidays,
        target_payment=target_payment_value,
    )


def export_to_json(path: Path, schedule: List[ScheduleEntry], summary: Dict[str, Any]) -> None:
    """Export schedule and summary to a JSON file."""
    # Convert schedule entries to serializable dicts
    sched_list = []
    for e in schedule:
        sched_list.append(
            {
                "period": e.period,
                "date": e.date.strftime("%Y-%m"),
                "starting_balance": float(e.starting_balance),
                "payment": float(e.payment),
                "principal": float(e.principal_payment),
                "interest": float(e.interest_payment),
                "overpayment": float(e.overpayment),
                "ending_balance": float(e.ending_balance),
                "tranche_disbursed": float(e.tranche_disbursed),
                "holiday": e.holiday,
            }
        )
    data = {"summary": summary, "schedule": sched_list}
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def export_to_csv(path: Path, schedule: List[ScheduleEntry]) -> None:
    """Export schedule to a CSV file."""
    header = [
        "Period",
        "Date",
        "Starting_Balance",
        "Payment",
        "Principal",
        "Interest",
        "Overpayment",
        "Ending_Balance",
        "Tranche_Disbursed",
        "Holiday",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for e in schedule:
            writer.writerow(
                [
                    e.period,
                    e.date.strftime("%Y-%m"),
                    float(e.starting_balance),
                    float(e.payment),
                    float(e.principal_payment),
                    float(e.interest_payment),
                    float(e.overpayment),
                    float(e.ending_balance),
                    float(e.tranche_disbursed),
                    e.holiday,
                ]
            )


@click.group()
def cli() -> None:
    """A command‑line loan calculator supporting complex scenarios."""
    pass


@cli.command()
@click.option("--principal", "-p", "principal", required=True, help="Total loan amount")
@click.option("--rate", "-r", "rate", required=True, type=float, help="Annual interest rate (percent)")
@click.option("--term", "-t", "term", required=True, type=int, help="Loan term in months")
@click.option("--type", "loan_type", type=click.Choice(["annuity", "decreasing"]), default="annuity", help="Installment type")
@click.option("--start-date", "-s", "start_date", required=True, help="First payment date (YYYY-MM)")
@click.option("--down-payment", "-d", "down_payment", help="Down payment amount")
@click.option("--tranche", "tranche", multiple=True, help="Tranche in YYYY-MM:PERCENT format")
@click.option("--overpayment", "overpayment", multiple=True, help="Overpayment in YYYY-MM:AMOUNT:TYPE format")
@click.option("--holiday", "holiday", multiple=True, help="Payment holiday month (YYYY-MM)")
@click.option(
    "--monthly-overpayment",
    "monthly_overpayment",
    help="Apply the same overpayment every month in AMOUNT:TYPE format. Example: --monthly-overpayment 500:term",
)
@click.option(
    "--constant-payment",
    "constant_payment",
    help="Target total monthly payment. The program will treat the difference between this amount and the scheduled installment as an overpayment (reduce installment).",
)
@click.option("--output", "output", type=str, help="Output file path (.json or .csv)")
def schedule(
    principal: str,
    rate: float,
    term: int,
    loan_type: str,
    start_date: str,
    down_payment: Optional[str],
    tranche: Tuple[str, ...],
    overpayment: Tuple[str, ...],
    holiday: Tuple[str, ...],
    monthly_overpayment: Optional[str],
    constant_payment: Optional[str],
    output: Optional[str],
) -> None:
    """Compute and print the full amortization schedule."""
    config = build_config_from_options(
        principal,
        rate,
        term,
        loan_type,
        start_date,
        down_payment,
        tranche,
        overpayment,
        holiday,
        monthly_overpayment,
        constant_payment,
    )
    schedule_entries, summary = compute_schedule(config)
    if output:
        path = Path(output)
        if path.suffix.lower() == ".json":
            export_to_json(path, schedule_entries, summary)
            click.echo(f"Schedule exported to {path}")
        elif path.suffix.lower() == ".csv":
            export_to_csv(path, schedule_entries)
            click.echo(f"Schedule exported to {path}")
        else:
            raise click.BadParameter("Unsupported output format; use .json or .csv")
    else:
        # Print summary and schedule
        print_summary(summary)
        # Limit schedule length printed to avoid flooding the terminal
        max_rows = 120
        if len(schedule_entries) > max_rows:
            click.echo(
                f"Schedule has {len(schedule_entries)} rows; showing first {max_rows} rows."
            )
            print_schedule(schedule_entries[:max_rows])
        else:
            print_schedule(schedule_entries)


@cli.command()
@click.option("--principal", "-p", "principal", required=True, help="Total loan amount")
@click.option("--rate", "-r", "rate", required=True, type=float, help="Annual interest rate (percent)")
@click.option("--term", "-t", "term", required=True, type=int, help="Loan term in months")
@click.option("--type", "loan_type", type=click.Choice(["annuity", "decreasing"]), default="annuity", help="Installment type")
@click.option("--start-date", "-s", "start_date", required=True, help="First payment date (YYYY-MM)")
@click.option("--down-payment", "-d", "down_payment", help="Down payment amount")
@click.option("--tranche", "tranche", multiple=True, help="Tranche in YYYY-MM:PERCENT format")
@click.option("--overpayment", "overpayment", multiple=True, help="Overpayment in YYYY-MM:AMOUNT:TYPE format")
@click.option("--holiday", "holiday", multiple=True, help="Payment holiday month (YYYY-MM)")
@click.option(
    "--monthly-overpayment",
    "monthly_overpayment",
    help="Apply the same overpayment every month in AMOUNT:TYPE format. Example: --monthly-overpayment 500:term",
)
@click.option(
    "--constant-payment",
    "constant_payment",
    help="Target total monthly payment. The program will treat the difference between this amount and the scheduled installment as an overpayment (reduce installment).",
)
@click.option("--output", "output", type=str, help="Output file path (.json)")
def summary(
    principal: str,
    rate: float,
    term: int,
    loan_type: str,
    start_date: str,
    down_payment: Optional[str],
    tranche: Tuple[str, ...],
    overpayment: Tuple[str, ...],
    holiday: Tuple[str, ...],
    monthly_overpayment: Optional[str],
    constant_payment: Optional[str],
    output: Optional[str],
) -> None:
    """Compute and print only the summary metrics for a loan."""
    config = build_config_from_options(
        principal,
        rate,
        term,
        loan_type,
        start_date,
        down_payment,
        tranche,
        overpayment,
        holiday,
        monthly_overpayment,
        constant_payment,
    )
    _, summary_data = compute_schedule(config)
    if output:
        path = Path(output)
        if path.suffix.lower() != ".json":
            raise click.BadParameter("Summary export must use .json extension")
        with path.open("w", encoding="utf-8") as f:
            json.dump({"summary": summary_data}, f, indent=2)
        click.echo(f"Summary exported to {path}")
    else:
        print_summary(summary_data)


@cli.command()
@click.option("--scenario1", "scenario1", required=True, help="First scenario options quoted string")
@click.option("--scenario2", "scenario2", required=True, help="Second scenario options quoted string")
def compare(scenario1: str, scenario2: str) -> None:
    """Compare two loan scenarios.

    Scenarios are provided as quoted option strings, for example:

        loan-calc compare --scenario1 "-p 500k -r 3.5 -t 360" --scenario2 "-p 500k -r 3.2 -t 300"
    """
    # A minimal parser to convert scenario option strings into arguments
    def parse_scenario_opts(opts: str) -> Dict[str, Any]:
        # Split by whitespace, respecting simple quotes
        import shlex

        tokens = shlex.split(opts)
        # We will simulate passing these tokens to click by mapping them to our
        # build_config_from_options signature
        params: Dict[str, Any] = {
            "principal": None,
            "rate": None,
            "term": None,
            "loan_type": "annuity",
            "start_date": None,
            "down_payment": None,
            "tranche": [],
            "overpayment": [],
            "holiday": [],
            "monthly_overpayment": None,
            "constant_payment": None,
        }
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token in ("-p", "--principal"):
                i += 1
                params["principal"] = tokens[i]
            elif token in ("-r", "--rate"):
                i += 1
                params["rate"] = float(tokens[i])
            elif token in ("-t", "--term"):
                i += 1
                params["term"] = int(tokens[i])
            elif token == "--type":
                i += 1
                params["loan_type"] = tokens[i]
            elif token == "--start-date":
                i += 1
                params["start_date"] = tokens[i]
            elif token == "--down-payment":
                i += 1
                params["down_payment"] = tokens[i]
            elif token == "--tranche":
                i += 1
                params["tranche"].append(tokens[i])
            elif token == "--overpayment":
                i += 1
                params["overpayment"].append(tokens[i])
            elif token == "--holiday":
                i += 1
                params["holiday"].append(tokens[i])
            elif token == "--monthly-overpayment":
                i += 1
                params["monthly_overpayment"] = tokens[i]
            elif token == "--constant-payment":
                i += 1
                params["constant_payment"] = tokens[i]
            else:
                raise click.BadParameter(f"Unknown option in scenario: {token}")
            i += 1
        # Fill defaults if missing
        required = ["principal", "rate", "term", "start_date"]
        for r in required:
            if params[r] is None:
                raise click.BadParameter(f"Scenario missing required option {r}")
        return params

    params1 = parse_scenario_opts(scenario1)
    params2 = parse_scenario_opts(scenario2)
    config1 = build_config_from_options(**params1)
    config2 = build_config_from_options(**params2)
    _, summary1 = compute_schedule(config1)
    _, summary2 = compute_schedule(config2)
    print_comparison(summary1, summary2)


if __name__ == "__main__":
    cli()