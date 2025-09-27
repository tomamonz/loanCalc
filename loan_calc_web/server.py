#!/usr/bin/env python3
"""
Minimal HTTP server for the loan calculator web interface.

This server uses only Python's standard library. It serves an HTML form where
users can input loan parameters and view the resulting summary and (truncated)
amortization schedule. The calculation logic reuses the ``loan_calc`` package.

To run the server, execute this file:

    python3 server.py

Then open http://localhost:8000 in your browser.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
import html
from pathlib import Path
import json
from decimal import Decimal

import sys
import os
from pathlib import Path

# Ensure the parent directory (repository root) is on sys.path so that the loan_calc package
# can be imported when this server is run directly without installation.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from loan_calc.main import build_config_from_options
from loan_calc.engine import compute_schedule


WEB_DIR = Path(__file__).resolve().parent


def load_file(path: Path) -> bytes:
    """Read a file relative to the web directory and return its bytes."""
    with open(path, "rb") as f:
        return f.read()


class LoanHandler(BaseHTTPRequestHandler):
    def _send_response(self, content: bytes, content_type: str = "text/html", status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path.startswith("/static/"):
            # Serve static files (CSS)
            file_path = WEB_DIR / self.path.lstrip("/")
            if file_path.exists() and file_path.is_file():
                content_type = "text/css" if file_path.suffix == ".css" else "application/octet-stream"
                self._send_response(load_file(file_path), content_type)
            else:
                self.send_error(404, "File not found")
            return
        # Otherwise serve index
        index_path = WEB_DIR / "templates" / "index.html"
        self._send_response(load_file(index_path))

    def do_POST(self) -> None:
        # Read and parse form data
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        data = parse_qs(body)

        def get_field(name: str, default: str | None = ""):
            return data.get(name, [default])[0]

        try:
            principal = get_field("principal").strip()
            rate = float(get_field("rate", "0"))
            term = int(get_field("term", "0"))
            loan_type = get_field("loan_type", "annuity")
            start_date = get_field("start_date").strip()
            down_payment = get_field("down_payment").strip() or None

            # Helper to split comma/newline separated fields
            def split_list(raw: str) -> list[str]:
                if not raw:
                    return []
                return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]

            tranches = split_list(get_field("tranches"))
            overpayments = split_list(get_field("overpayments"))
            holidays = split_list(get_field("holidays"))
            monthly_overpayment = get_field("monthly_overpayment").strip() or None
            constant_payment = get_field("constant_payment").strip() or None

            config = build_config_from_options(
                principal,
                rate,
                term,
                loan_type,
                start_date,
                down_payment,
                tuple(tranches),
                tuple(overpayments),
                tuple(holidays),
                monthly_overpayment,
                constant_payment,
            )
            sched, summ = compute_schedule(config)

            # Build HTML response with summary and truncated schedule
            html_parts: list[str] = []
            html_parts.append("<html><head><meta charset='utf-8'><link rel='stylesheet' href='/static/style.css'><title>Loan Results</title></head><body><div class='container'>")
            html_parts.append("<h1>Loan Results</h1>")
            # Summary table
            html_parts.append("<h2>Summary</h2>")
            html_parts.append("<table class='summary-table'><tbody>")
            def add_row(label: str, value: str) -> None:
                html_parts.append(f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>")
            add_row("Principal financed", f"{summ['principal_financed']:.2f}")
            add_row("Total interest", f"{summ['total_interest']:.2f}")
            if summ.get("total_overpayment", 0) > 0:
                add_row("Total overpayment", f"{summ['total_overpayment']:.2f}")
            add_row("Total cost", f"{summ['total_cost']:.2f}")
            add_row("APR (approx)", f"{summ['apr'] * 100:.2f} %")
            add_row("Original end date", summ['original_end_date'])
            add_row("New end date", summ['new_end_date'])
            add_row("Payments made", str(summ['payments_made']))
            add_row("Highest payment", f"{summ['max_payment']:.2f}")
            html_parts.append("</tbody></table>")

            # Schedule table truncated to first 120 rows
            html_parts.append("<h2>Amortization Schedule</h2>")
            html_parts.append("<div class='schedule-wrapper'><table class='schedule-table'><thead><tr>")
            headers = ["Period", "Date", "Start Bal", "Payment", "Principal", "Interest", "Overpay", "End Bal", "Holiday"]
            for h in headers:
                html_parts.append(f"<th>{html.escape(h)}</th>")
            html_parts.append("</tr></thead><tbody>")
            max_rows = 120
            truncated_count = 0
            for i, row in enumerate(sched):
                if i >= max_rows:
                    truncated_count = len(sched) - max_rows
                    break
                html_parts.append("<tr>")
                html_parts.append(f"<td>{row.period}</td>")
                html_parts.append(f"<td>{row.date.strftime('%Y-%m')}</td>")
                html_parts.append(f"<td>{row.starting_balance:.2f}</td>")
                html_parts.append(f"<td>{row.payment:.2f}</td>")
                html_parts.append(f"<td>{row.principal_payment:.2f}</td>")
                html_parts.append(f"<td>{row.interest_payment:.2f}</td>")
                html_parts.append(f"<td>{row.overpayment:.2f}</td>")
                html_parts.append(f"<td>{row.ending_balance:.2f}</td>")
                html_parts.append(f"<td>{'Yes' if row.holiday else 'No'}</td>")
                html_parts.append("</tr>")
            html_parts.append("</tbody></table>")
            if truncated_count:
                html_parts.append(f"<p class='truncate-note'>Showing first {max_rows} rows. {truncated_count} more rows truncated.</p>")
            html_parts.append("</div>")
            html_parts.append("<p><a href='/'>Back</a></p>")
            html_parts.append("</div></body></html>")
            content = "".join(html_parts).encode("utf-8")
            self._send_response(content, content_type="text/html")
        except Exception as exc:
            content = f"<html><body><h1>Error</h1><p>{html.escape(str(exc))}</p><p><a href='/'>Back</a></p></body></html>".encode(
                "utf-8"
            )
            self._send_response(content, content_type="text/html", status=500)


def run_server():
    port = 8710
    server_address = ("", port)
    httpd = HTTPServer(server_address, LoanHandler)
    print(f"Serving on http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()