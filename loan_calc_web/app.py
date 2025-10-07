import json
import os
from uuid import uuid4
from flask import Flask, render_template, request, session, redirect, url_for

from loan_calc.main import build_config_from_options
from loan_calc.engine import compute_schedule

app = Flask(__name__)
app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "1")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

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


def _serialize_schedule(schedule):
    """Convert schedule entries into JSON-serialisable dictionaries for charts."""
    serialized = []
    for entry in schedule:
        serialized.append(
            {
                "period": entry.period,
                "date": entry.date.strftime("%Y-%m"),
                "payment": float(entry.payment),
                "principal": float(entry.principal_payment),
                "interest": float(entry.interest_payment),
                "overpayment": float(entry.overpayment),
                "balance": float(entry.ending_balance),
            }
        )
    return serialized


def _store_comparison_scenario(name: str, summary: dict, schedule: list[dict]) -> None:
    comparison_summary = {k: v for k, v in summary.items() if k != "comparison"}
    scenarios = session.get("comparison_scenarios", [])
    scenarios.append(
        {
            "id": str(uuid4()),
            "name": name,
            "summary": comparison_summary,
            "schedule": schedule,
        }
    )
    session["comparison_scenarios"] = scenarios
    session.modified = True


@app.route("/", methods=["GET", "POST"])
def index():
    summary = None
    schedule = None
    full_schedule = None
    error = None
    show_full_schedule = False
    currency_code = "PLN"
    action = "run"

    if request.method == "POST":
        action = request.form.get("action", "run")
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
            if summary and action == "add_to_comparison":
                scenario_name = request.form.get("scenario_name", "").strip()
                if not scenario_name:
                    scenarios = session.get("comparison_scenarios", [])
                    scenario_name = f"Scenario {len(scenarios) + 1}"
                serialized_schedule = _serialize_schedule(full_schedule or [])
                _store_comparison_scenario(scenario_name, summary, serialized_schedule)
        except Exception as exc:
            error = str(exc)

    currency_meta = CURRENCY_OPTIONS.get(currency_code, CURRENCY_OPTIONS["PLN"])
    comparison_scenarios = session.get("comparison_scenarios", [])
    comparison_payload = json.dumps(comparison_scenarios)
    current_schedule_payload = json.dumps(_serialize_schedule(full_schedule or [])) if full_schedule else "null"

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
        comparison_scenarios=comparison_scenarios,
        comparison_payload=comparison_payload,
        current_schedule_payload=current_schedule_payload,
        last_action=action,
    )


@app.post("/comparison/remove")
def remove_comparison():
    scenario_id = request.form.get("scenario_id")
    scenarios = session.get("comparison_scenarios", [])
    if scenario_id and scenarios:
        scenarios = [s for s in scenarios if s.get("id") != scenario_id]
        session["comparison_scenarios"] = scenarios
        session.modified = True
    return redirect(url_for("index"))


@app.post("/comparison/clear")
def clear_comparisons():
    if "comparison_scenarios" in session:
        session.pop("comparison_scenarios")
        session.modified = True
    return redirect(url_for("index"))


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8710"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
