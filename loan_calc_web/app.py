import json
import os
from uuid import uuid4
from flask import Flask, render_template, request, session, redirect, url_for

from loan_calc.main import build_config_from_options
from loan_calc.engine import compute_schedule
from loan_calc_web.comparison_store import create_store_from_env

app = Flask(__name__)
app.config["ASSET_VERSION"] = os.environ.get("ASSET_VERSION", "1")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
comparison_store = create_store_from_env(os.environ.get("COMPARISON_DATABASE_URL"))

CURRENCY_OPTIONS = {
    'PLN': {'label': 'Polish z?oty', 'prefix': '', 'suffix': ' z?'},
    'USD': {'label': 'US dollar', 'prefix': '$', 'suffix': ''},
    'EUR': {'label': 'Euro', 'prefix': '?', 'suffix': ''},
    'GBP': {'label': 'British pound', 'prefix': '?', 'suffix': ''},
}


def _ensure_user_token() -> str:
    token = session.get("user_token")
    if not token:
        token = uuid4().hex
        session["user_token"] = token
        session.modified = True
    return token


def _normalized_currency(form) -> str:
    code = form.get("currency", "PLN").upper()
    return code if code in CURRENCY_OPTIONS else "PLN"


def _form_to_config(form):
    principal = form.get("principal", "").strip()
    rate = float(form.get("rate", 0.0))
    term = int(form.get("term", 0))
    loan_type = form.get("loan_type", "annuity")
    start_date = form.get("start_date", "")
    down_payment = form.get("down_payment", "").strip() or None
    tranche_list = parse_form_list(form.get("tranches", ""))
    overpayment_list = parse_form_list(form.get("overpayments", ""))
    holiday_list = parse_form_list(form.get("holidays", ""))
    monthly_overpayment = form.get("monthly_overpayment", "").strip() or None
    constant_payment = form.get("constant_payment", "").strip() or None

    return build_config_from_options(
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


def _summaries_for_view(summary: dict, schedule: list, show_full_schedule: bool):
    if not summary:
        return summary, []
    if show_full_schedule:
        summary.pop("truncated", None)
        return summary, schedule
    preview = schedule[:120]
    if len(schedule) > 120:
        summary["truncated"] = len(schedule) - len(preview)
    return summary, preview


def _run_analysis(form, show_full_schedule: bool):
    config = _form_to_config(form)
    full_schedule, summary = compute_schedule(config)
    serialized_schedule = _serialize_schedule(full_schedule)
    summary, schedule_view = _summaries_for_view(summary, full_schedule, show_full_schedule)
    return summary, schedule_view, full_schedule, serialized_schedule


def _handle_save_action(user_token: str, form, summary: dict, serialized_schedule: list[dict]) -> None:
    scenario_name = form.get("scenario_name", "").strip() or "Scenario"
    scenario_id = uuid4().hex
    summary_copy = {k: v for k, v in summary.items() if k not in {"comparison", "truncated"}}
    comparison_store.add_scenario(user_token, scenario_id, scenario_name, summary_copy, serialized_schedule)


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


@app.route("/", methods=["GET", "POST"])
def index():
    summary = None
    schedule = None
    full_schedule = None
    error = None
    show_full_schedule = False
    currency_code = "PLN"
    action = "run"

    user_token = _ensure_user_token()

    if request.method == "POST":
        action = request.form.get("action", "run")
        currency_code = _normalized_currency(request.form)
        show_full_schedule = request.form.get("show_full_schedule") == "1"
        try:
            summary, schedule, full_schedule, serialized_schedule = _run_analysis(
                request.form, show_full_schedule
            )
            if summary and action == "add_to_comparison":
                _handle_save_action(user_token, request.form, summary, serialized_schedule)
        except Exception as exc:
            error = str(exc)

    currency_meta = CURRENCY_OPTIONS.get(currency_code, CURRENCY_OPTIONS["PLN"])
    comparison_scenarios = comparison_store.list_scenarios(user_token)
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
    user_token = session.get("user_token")
    comparison_store.remove_scenario(user_token, scenario_id)
    return redirect(url_for("index"))


@app.post("/comparison/clear")
def clear_comparisons():
    user_token = session.get("user_token")
    comparison_store.clear_scenarios(user_token)
    return redirect(url_for("index"))


if __name__ == "__main__":
    print("Starting Loan Calculator web app...")
    app.run(host="0.0.0.0", port=8710, debug=True)