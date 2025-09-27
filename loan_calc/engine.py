"""Core calculation engine for the loan calculator.

This module implements the financial logic required to build amortization
schedules for both annuity (equal) and decreasing installment loans.  It
supports overpayments, holiday (payment-free) months and phased drawdowns
(tranches). Results are returned as a list of ``ScheduleEntry`` objects along
with a summary dictionary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext
from typing import Dict, Iterable, List, Tuple

from .data_models import LoanConfig, ScheduleEntry, Tranche, Overpayment
from .utils import add_months

getcontext().prec = 28  # increase precision for financial calculations


def _calculate_annuity_payment(principal: Decimal, rate_per_month: Decimal, term: int) -> Decimal:
    """Return the annuity (equal installment) monthly payment for a loan.

    The formula is:

        payment = P * (i * (1 + i)^n) / ((1 + i)^n - 1)

    where ``P`` is the principal, ``i`` is the monthly interest rate and
    ``n`` is the number of payments. When the interest rate is zero, the
    payment simplifies to ``P / n``.
    """
    if term <= 0:
        raise ValueError("Term must be positive")
    if rate_per_month == 0:
        return principal / Decimal(term)
    factor = (1 + rate_per_month) ** term
    return principal * (rate_per_month * factor) / (factor - 1)


def _sort_tranches(tranches: List[Tranche]) -> List[Tranche]:
    return sorted(tranches, key=lambda t: t.date)


def _prepare_overpayments(overpayments: Iterable[Overpayment]) -> Dict[date, List[Overpayment]]:
    """Group overpayments by date for quick lookup."""
    mapping: Dict[date, List[Overpayment]] = {}
    for op in overpayments:
        mapping.setdefault(op.date, []).append(op)
    return mapping


def _prepare_tranches(tranches: Iterable[Tranche]) -> Dict[date, Decimal]:
    """Return a mapping of dates to cumulative percentage disbursed.

    The input tranches specify cumulative percentages. The returned dict
    contains the same percentages keyed by their dates.
    """
    mapping: Dict[date, Decimal] = {}
    for t in tranches:
        mapping[t.date] = t.percent
    return mapping


def compute_schedule(config: LoanConfig) -> Tuple[List[ScheduleEntry], Dict[str, object]]:
    """Compute the amortization schedule and summary for a loan.

    Parameters
    ----------
    config: LoanConfig
        The loan configuration. The ``principal`` value should be the total
        loan amount *before* any down payment; the ``down_payment`` reduces
        the financed amount.

    Returns
    -------
    schedule: List[ScheduleEntry]
        A list of schedule entries, one per month. Entries for holiday months
        have ``payment`` and ``principal_payment`` equal to zero and reflect
        interest capitalization.
    summary: Dict[str, object]
        Aggregate metrics including total interest, total cost, APR,
        original end date, new end date and number of payments.
    """
    # Financed principal after subtracting down payment
    financed_principal = config.principal - config.down_payment
    if financed_principal <= 0:
        raise ValueError("Financed principal must be positive after down payment")

    # Convert annual rate from percent to monthly decimal
    rate_per_month = (config.rate / Decimal(100)) / Decimal(12)

    # Prepare tranches and overpayments
    tranches_sorted = _sort_tranches(config.tranches)
    tranche_map = _prepare_tranches(tranches_sorted)
    overpayment_map = _prepare_overpayments(config.overpayments)
    holiday_set = {d for d in config.holidays}

    # Determine the earliest date: either earliest tranche date or start date
    earliest_date = config.start_date
    if tranches_sorted:
        earliest_date = min(earliest_date, min(t.date for t in tranches_sorted))

    # Track the current disbursed percentage and principal prior to start_date
    current_percent = Decimal('0')
    disbursed_principal = Decimal('0')
    capitalized_interest = Decimal('0')
    dt = earliest_date
    # Move month by month until the month before the start date
    while dt < config.start_date:
        # Apply tranche disbursement at the beginning of the month
        if dt in tranche_map:
            new_percent = tranche_map[dt]
            # Additional percentage to disburse
            delta_percent = new_percent - current_percent
            if delta_percent < 0:
                # If percentages decrease out of order, ignore
                delta_percent = Decimal('0')
            disbursed_principal += financed_principal * delta_percent
            current_percent = new_percent
        # Accrue interest on disbursed principal
        monthly_interest = disbursed_principal * rate_per_month
        capitalized_interest += monthly_interest
        dt = add_months(dt, 1)
    # Final principal at start date: disbursed principal + capitalized interest
    principal = disbursed_principal + capitalized_interest
    # If no tranches were specified, assume full principal is disbursed at start
    if not tranches_sorted:
        principal = financed_principal

    schedule: List[ScheduleEntry] = []
    period = 1
    remaining_term = config.term
    loan_type = config.loan_type.lower()

    # Compute initial monthly payment for annuity
    if loan_type == 'annuity':
        monthly_payment = _calculate_annuity_payment(principal, rate_per_month, remaining_term)
    else:
        # constant principal component for decreasing loans
        constant_principal = principal / Decimal(remaining_term)
        monthly_payment = constant_principal + principal * rate_per_month

    current_date = config.start_date

    total_interest_paid = Decimal('0')
    total_overpayment = Decimal('0')
    total_principal_paid = Decimal('0')
    # Record new disbursements after start_date
    # In many mortgage structures disbursements may occur after start; treat similarly to pre-start
    while (principal > Decimal('0.01')) and (period <= config.term * 2):
        starting_balance = principal
        tranche_disbursed = Decimal('0')
        # Apply tranche disbursement at beginning of this month if any tranches occur on current_date
        # When a new tranche is disbursed on or after the start date, the principal increases. For
        # annuity loans we must recompute the monthly payment based on the new principal and
        # remaining term to avoid a large balloon payment at the end of the schedule. For
        # decreasing loans, we recalculate the constant principal component.
        if current_date in tranche_map:
            new_percent = tranche_map[current_date]
            delta_percent = new_percent - current_percent
            if delta_percent > 0:
                # Additional principal released this month
                additional = financed_principal * delta_percent
                principal += additional
                disbursed_principal += additional
                tranche_disbursed = additional
                current_percent = new_percent
                # Recalculate monthly payment when a tranche is disbursed during the schedule
                # (i.e., on or after the start date). Without this recalculation, the initial payment
                # computed before all tranches may be too low and leave a large residual at the end.
                if loan_type == 'annuity':
                    # Only recalc if there are payments left in the term
                    if remaining_term > 0:
                        monthly_payment = _calculate_annuity_payment(principal, rate_per_month, remaining_term)
                else:
                    # Decreasing loan: update constant principal and monthly payment
                    if remaining_term > 0:
                        constant_principal = principal / Decimal(remaining_term)
                        monthly_payment = constant_principal + principal * rate_per_month

        # Holiday: no payment; interest is capitalized
        if current_date in holiday_set:
            interest_payment = principal * rate_per_month
            principal += interest_payment
            # Record entry with no payment
            entry = ScheduleEntry(
                period=period,
                date=current_date,
                starting_balance=starting_balance,
                payment=Decimal('0'),
                principal_payment=Decimal('0'),
                interest_payment=interest_payment,
                overpayment=Decimal('0'),
                ending_balance=principal,
                tranche_disbursed=tranche_disbursed,
                holiday=True,
            )
            schedule.append(entry)
            total_interest_paid += interest_payment
            # do not decrement remaining_term; extend schedule
            current_date = add_months(current_date, 1)
            period += 1
            continue

        # Standard payment period
        if loan_type == 'annuity':
            # recalc payment if necessary (for reduce_installment overpayments)
            base_payment = monthly_payment
            interest_payment = principal * rate_per_month
            principal_payment = base_payment - interest_payment
        else:
            # decreasing
            # constant principal component; recalc if changed (e.g. due to reduce_installment overpayment)
            principal_component = constant_principal if 'constant_principal' in locals() else principal / Decimal(remaining_term)
            interest_payment = principal * rate_per_month
            base_payment = principal_component + interest_payment
            principal_payment = principal_component

        overpayment_total = Decimal('0')
        reduce_installment_flag = False
        # Apply overpayments scheduled for this month
        if current_date in overpayment_map:
            for op in overpayment_map[current_date]:
                overpayment_total += op.amount
                total_overpayment += op.amount
                if op.type == 'installment':
                    reduce_installment_flag = True
            principal_payment += overpayment_total

        # Apply dynamic overpayment to meet a constant target payment (if specified). This
        # feature allows the user to specify a fixed monthly budget (e.g., "6000") and
        # automatically allocate any difference between the scheduled installment and this
        # budget to an extra principal payment. The dynamic overpayment always behaves
        # like a "reduce_installment" overpayment, so future payments will be recalculated.
        if config.target_payment is not None:
            # Total cash outflow so far for this period (base payment plus any explicit
            # overpayments). We do not include dynamic overpayment yet.
            current_outflow = base_payment + overpayment_total
            diff = config.target_payment - current_outflow
            if diff > Decimal('0'):
                # Additional money to apply to principal this month
                principal_payment += diff
                overpayment_total += diff
                total_overpayment += diff
                reduce_installment_flag = True
        # Apply payment to principal
        principal -= principal_payment
        total_principal_paid += principal_payment
        total_interest_paid += interest_payment

        # Round very small residuals down to zero. After applying the payment,
        # the principal might remain as an extremely small positive value due
        # to floating point precision errors (e.g., 2e-23). Treat anything
        # less than half a cent as zero to prevent phantom extra periods.
        if principal.copy_abs() < Decimal('0.005'):
            principal = Decimal('0')

        # Recalculate monthly payment for reduce_installment after applying payment
        if reduce_installment_flag and principal > 0 and remaining_term > 1:
            # For annuity loans re‑amortize with same rate and one less remaining_term
            if loan_type == 'annuity':
                remaining_term -= 1
                monthly_payment = _calculate_annuity_payment(principal, rate_per_month, remaining_term)
            else:
                remaining_term -= 1
                constant_principal = principal / Decimal(remaining_term)
                monthly_payment = constant_principal + principal * rate_per_month
        else:
            # For reduce_term or no overpayment we simply decrement remaining_term
            remaining_term -= 1

        # If the payment overshoots the principal (last payment), adjust for negative principal
        if principal < 0:
            # adjust the last payment to bring principal exactly to zero
            adjustment = -principal
            principal_payment -= adjustment
            base_payment -= adjustment
            principal = Decimal('0')

        entry = ScheduleEntry(
            period=period,
            date=current_date,
            starting_balance=starting_balance,
            payment=base_payment if base_payment > 0 else Decimal('0'),
            principal_payment=principal_payment,
            interest_payment=interest_payment,
            overpayment=overpayment_total,
            ending_balance=principal,
            tranche_disbursed=tranche_disbursed,
            holiday=False,
        )
        schedule.append(entry)

        # Move to next month
        current_date = add_months(current_date, 1)
        period += 1

        # Stop if no remaining term for annuity loans to avoid infinite loop
        if remaining_term <= 0 and principal > 0:
            # Force final payment to clear remaining principal
            interest_payment = principal * rate_per_month
            base_payment = principal + interest_payment
            principal_payment = principal
            total_principal_paid += principal_payment
            total_interest_paid += interest_payment
            principal = Decimal('0')
            entry = ScheduleEntry(
                period=period,
                date=current_date,
                starting_balance=schedule[-1].ending_balance,
                payment=base_payment,
                principal_payment=principal_payment,
                interest_payment=interest_payment,
                overpayment=Decimal('0'),
                ending_balance=Decimal('0'),
                tranche_disbursed=Decimal('0'),
                holiday=False,
            )
            schedule.append(entry)
            current_date = add_months(current_date, 1)
            period += 1
            break

    # Compute summary metrics
    original_end_date = add_months(config.start_date, config.term - 1)
    new_end_date = schedule[-1].date if schedule else config.start_date
    total_cost = financed_principal + total_interest_paid
    apr = (1 + rate_per_month) ** 12 - 1  # approximate effective annual rate
    payments_made = sum(1 for s in schedule if not s.holiday and s.payment > 0)

    # Compute the highest (non-zero) payment amount. Holidays have payment=0, so skip those.
    # In annuity loans the base payment is constant unless recalculated due to reduce_installment overpayments.
    # For decreasing loans the first payment is typically the largest. Overpayments are not included in the
    # payment column, so base payments can still vary.
    try:
        # Highest cash outflow: base payment plus overpayment. Holidays have zero payment and zero
        # overpayment, so they will not affect the maximum.
        max_payment = max(
            float(s.payment + s.overpayment) for s in schedule if (s.payment + s.overpayment) > 0
        )
    except ValueError:
        max_payment = 0.0

    summary = {
        "principal_financed": float(financed_principal),
        "total_interest": float(total_interest_paid),
        "total_overpayment": float(total_overpayment),
        "total_cost": float(total_cost),
        "apr": float(apr),
        "term_months": config.term,
        "original_end_date": original_end_date.strftime("%Y-%m"),
        "new_end_date": new_end_date.strftime("%Y-%m"),
        "payments_made": payments_made,
        "max_payment": max_payment,
    }

    return schedule, summary