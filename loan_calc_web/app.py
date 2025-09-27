from flask import Flask, render_template, request
from decimal import Decimal
from pathlib import Path

from loan_calc.main import build_config_from_options
from loan_calc.engine import compute_schedule

app = Flask(__name__)


def parse_form_list(value: str) -> list[str]:
    """Parse a comma or whitespace separated list of entries from a form field.

    Returns a list of trimmed strings, skipping any empty entries.
    """
    if not value:
        return []
    # split by comma or newline
    parts = [p.strip() for p in value.replace("\n", ",").split(",")]
    return [p for p in parts if p]


@app.route("/", methods=["GET", "POST"])
def index():
    summary = None
    schedule = None
    error = None
    if request.method == "POST":
        try:
            principal = request.form.get("principal", "").strip()
            rate = float(request.form.get("rate", 0.0))
            term = int(request.form.get("term", 0))
            loan_type = request.form.get("loan_type", "annuity")
            start_date = request.form.get("start_date", "")
            down_payment = request.form.get("down_payment", "").strip() or None
            # tranches and overpayments as comma/newline separated strings
            tranche_list = parse_form_list(request.form.get("tranches", ""))
            overpayment_list = parse_form_list(request.form.get("overpayments", ""))
            holiday_list = parse_form_list(request.form.get("holidays", ""))
            monthly_overpayment = request.form.get("monthly_overpayment", "").strip() or None
            constant_payment = request.form.get("constant_payment", "").strip() or None

            config = build_config_from_options(
                principal,
                rate,
                term,
                loan_type,
                start_date,
                down_payment,
                tuple(tranche_list),
                tuple(overpayment_list),
                tuple(holiday_list),
                monthly_overpayment,
                constant_payment,
            )
            sched, summ = compute_schedule(config)
            summary = summ
            # Show only first 120 rows to avoid huge tables
            schedule = sched[:120]
            if len(sched) > 120:
                summary["truncated"] = len(sched) - 120
        except Exception as exc:
            error = str(exc)
    return render_template(
        "index.html",
        summary=summary,
        schedule=schedule,
        error=error,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8710, debug=True)