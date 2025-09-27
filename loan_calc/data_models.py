"""Data models for the loan calculator.

This module defines dataclasses representing the different entities used by the
calculator: tranches (phased disbursements), overpayments, the overall loan
configuration and individual schedule entries. Using dataclasses makes it easy
to construct, inspect and serialize these structures.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional


@dataclass
class Tranche:
    """A tranche is a phased disbursement of the loan principal.

    Attributes
    ----------
    date: date
        The date (year and month) when the tranche becomes active. Dates are
        normalized to the first day of the month when parsed.
    percent: Decimal
        The percentage of the total principal that has been disbursed by
        `date`. For example, a tranche with percent=Decimal("0.8") means 80 %
        of the principal is active as of that date.
    """

    date: date
    percent: Decimal


@dataclass
class Overpayment:
    """Represents an extra payment applied to the principal.

    Attributes
    ----------
    date: date
        The date (year and month) when the overpayment is applied.
    amount: Decimal
        The amount of additional money applied to the principal.
    type: str
        The overpayment type. ``"term"`` means reduce the loan term while
        keeping the monthly payment constant. ``"installment"`` means reduce
        the future monthly payment by re‑amortizing the remaining balance.
    """

    date: date
    amount: Decimal
    type: str  # "term" or "installment"


@dataclass
class LoanConfig:
    """Configuration of a loan.

    This configuration collects all user inputs into a single object, making
    it easy to pass around and serialize. The principal value should already
    account for any down payment (i.e. it is the financed amount).
    """

    principal: Decimal
    rate: Decimal  # annual nominal interest rate in percent
    term: int  # term in months
    start_date: date  # first payment date (month/year)
    loan_type: str  # 'annuity' or 'decreasing'
    down_payment: Decimal
    tranches: List[Tranche]
    overpayments: List[Overpayment]
    holidays: List[date]

    # Optional constant payment target. When set, the engine will attempt to keep the
    # total monthly cash outflow equal to ``target_payment``. Any difference between
    # the regular installment (payment) and this target will be treated as an
    # additional overpayment (reduce_installment) and will cause future payments to
    # decrease. If the target is less than the required installment, no dynamic
    # overpayment is applied (the user cannot pay less than the required amount).
    target_payment: Optional[Decimal] = None


@dataclass
class ScheduleEntry:
    """An entry in the amortization schedule.

    Each entry corresponds to one month. Even during interest‑only phases or
    holidays, an entry is recorded so that the timeline is clear. When
    ``holiday`` is True, ``payment`` and ``principal`` will be zero.
    """

    period: int
    date: date
    starting_balance: Decimal
    payment: Decimal
    principal_payment: Decimal
    interest_payment: Decimal
    overpayment: Decimal
    ending_balance: Decimal
    tranche_disbursed: Decimal
    holiday: bool