import os
from flask import Flask, render_template, request
from decimal import Decimal

from loan_calc.main import build_config_from_options
from loan_calc.engine import compute_schedule

app = Flask(__name__)
app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "1")

CURRENCY_OPTIONS = {
    'PLN': {'label': 'Polish z?oty', 'prefix': '', 'suffix': ' z?'},
    'USD': {'label': 'US dollar', 'prefix': '$', 'suffix': ''},
    'EUR': {'label': 'Euro', 'prefix': '?', 'suffix': ''},
    'GBP': {'label': 'British pound', 'prefix': '?', 'suffix': ''},
}

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
    full_schedule = None
    error = None
    show_full_schedule = False
    currency_code = "PLN"

    if request.method == "POST":
        currency_code = request.form.get("currency", "PLN").upper()
        if currency_code not in CURRENCY_OPTIONS:
            currency_code = "PLN"
        show_full_schedule = request.form.get("show_full_schedule") == "1"
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
            full_schedule = sched
            if show_full_schedule:
                schedule = sched
                summary.pop("truncated", None)
            else:
                schedule = sched[:120]
                if len(sched) > 120:
                    summary["truncated"] = len(sched) - len(schedule)
        except Exception as exc:
            error = str(exc)

    currency_meta = CURRENCY_OPTIONS.get(currency_code, CURRENCY_OPTIONS["PLN"])

    return render_template(
        "index.html",
        summary=summary,
        schedule=schedule,
        full_schedule=full_schedule,
        show_full_schedule=show_full_schedule,
        error=error,
        currency_code=currency_code,
        currency_options=CURRENCY_OPTIONS,
        currency_prefix=currency_meta["prefix"],
        currency_suffix=currency_meta["suffix"],
        asset_version=app.config["ASSET_VERSION"],
    )


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8710"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
