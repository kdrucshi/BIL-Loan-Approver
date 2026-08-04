"""
Report generation - Report.md. Two formats, two audiences:
- PDF: aggregates only (run_meta + GROUP BY queries), never renders all
  100,000 rows.
- CSV: one row per loan, streamed from the loans/rule_results/audit_events
  join, never pre-aggregated and never loaded fully into memory first.

Both are generated per run_id, so a past run can still be re-exported.
"""

import csv
import io
import json
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from pipeline.db import get_connection
from app.queries import post_review_compliance as _post_review_compliance


def _disposition_counts(conn, run_id: str) -> dict:
    rows = conn.execute(
        """
        SELECT json_extract(meta, '$.rule') AS rule, message, COUNT(*) AS n
        FROM audit_events
        WHERE run_id = ? AND source = 'reviewer'
        GROUP BY rule, message
        """,
        (run_id,),
    ).fetchall()

    fixed_manual = fixed_ai = ignored = removed = 0
    for r in rows:
        if r["message"] == "manual_fix":
            fixed_manual += r["n"]
        elif r["message"] == "accepted_ai_fix":
            fixed_ai += r["n"]
        elif r["message"] == "ignored":
            ignored += r["n"]
        elif r["message"] == "removed":
            removed += r["n"]

    return {
        "fixed_manual": fixed_manual,
        "fixed_ai": fixed_ai,
        "ignored": ignored,
        "removed": removed,
    }


def _rescue_note(conn, run_id: str, removed: int) -> str:
    """'X failed Rule 1 at evaluation; Y were rescued by a currency fix and
    re-check; Z were genuinely removed.' (Report.md 2.4)"""
    row = conn.execute("SELECT rule1_fails FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    raw_rule1_fails = row["rule1_fails"] if row else 0
    rescued = raw_rule1_fails - removed
    return (
        f"{raw_rule1_fails} failed Rule 1 at evaluation; {rescued} were rescued "
        f"by a currency fix and re-check; {removed} were genuinely removed."
    )


def _portfolio(conn, top_n: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT company_name, hq_country, COUNT(*) AS n_loans,
               SUM(CAST(loan_value AS REAL)) AS total_value, loan_currency
        FROM loans GROUP BY company_name ORDER BY total_value DESC LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_report_data(run_id: str) -> dict:
    conn = get_connection()
    run_meta = conn.execute("SELECT * FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    if run_meta is None:
        raise ValueError(f"Run '{run_id}' not found")
    run_meta = dict(run_meta)

    disposition = _disposition_counts(conn, run_id)
    total = run_meta["total_loans"]
    any_fail = run_meta["rule1_fails"] + run_meta["rule2_fails"] + run_meta["rule3_fails"]  # illustrative only; see /api/dashboard for exact overlap-safe count
    resolved_count = sum(disposition.values())

    return {
        "run_id": run_id,
        "started_at": run_meta["started_at"],
        "completed_at": run_meta["completed_at"],
        "total_loans": total,
        "fx_rate_date": run_meta["fx_rate_date"],
        "fx_source": run_meta["fx_source"],
        "fx_stale": bool(run_meta["fx_stale"]),
        "pre_review_compliance": run_meta["pre_review_compliance"],
        "post_review_compliance": _post_review_compliance(conn, run_id, total),
        "rules": [
            {"rule": 1, "name": "Minimum loan value", "passed": total - run_meta["rule1_fails"], "failed": run_meta["rule1_fails"]},
            {"rule": 2, "name": "Currency matches HQ", "passed": total - run_meta["rule2_fails"], "failed": run_meta["rule2_fails"]},
            {"rule": 3, "name": "Asset coverage", "passed": total - run_meta["rule3_fails"], "failed": run_meta["rule3_fails"]},
        ],
        "disposition": disposition,
        "rescue_note": _rescue_note(conn, run_id, disposition["removed"]),
        "portfolio": _portfolio(conn),
    }


def generate_pdf(run_id: str) -> bytes:
    data = build_report_data(run_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Loan Compliance Report", styles["Title"]))
    story.append(Paragraph(f"Run {data['run_id']} - {data['started_at']} to {data['completed_at']}", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph(
        f"FX rates: {data['fx_source']} dated {data['fx_rate_date']}"
        + (" (STALE - fallback rate)" if data["fx_stale"] else ""),
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Headline compliance score", styles["Heading2"]))
    pre = data["pre_review_compliance"]
    post = data["post_review_compliance"]
    delta = f"+{post - pre:.2f}" if post is not None else "n/a"
    story.append(Paragraph(
        f"Pre-review: {pre}% &nbsp;&nbsp; Post-review: {post if post is not None else 'n/a'}% "
        f"&nbsp;&nbsp; Delta: {delta} pts",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Per-rule breakdown", styles["Heading2"]))
    rule_table_data = [["Rule", "Name", "Passed", "Failed", "Fail %"]]
    for r in data["rules"]:
        fail_pct = round(100 * r["failed"] / data["total_loans"], 2) if data["total_loans"] else 0
        rule_table_data.append([str(r["rule"]), r["name"], f"{r['passed']:,}", f"{r['failed']:,}", f"{fail_pct}%"])
    story.append(_styled_table(rule_table_data))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Disposition summary", styles["Heading2"]))
    d = data["disposition"]
    disp_table = [
        ["Fixed manually", str(d["fixed_manual"])],
        ["Fixed via accepted AI suggestion", str(d["fixed_ai"])],
        ["Ignored", str(d["ignored"])],
        ["Removed (Rule 1, post-recheck)", str(d["removed"])],
    ]
    story.append(_styled_table([["Disposition", "Count"]] + disp_table))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(data["rescue_note"], styles["Italic"]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Portfolio summary - top companies by exposure", styles["Heading2"]))
    port_table = [["Company", "HQ country", "# loans", "Total loan value"]]
    for p in data["portfolio"]:
        port_table.append([
            p["company_name"], p["hq_country"], str(p["n_loans"]),
            f"{p['total_value']:,.2f} {p['loan_currency']}",
        ])
    story.append(_styled_table(port_table))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Methodology", styles["Heading2"]))
    story.append(Paragraph(
        "Country-to-currency table: static, hand-built (Evaluation_Engine.md section 6). "
        "Rule engine: OPA / Rego, package 'compliance'. "
        "FX fallback: Frankfurter (primary) -> exchangerate.host (secondary) -> "
        "last cached rate (flagged stale) if both are unavailable.",
        styles["Normal"],
    ))

    doc.build(story)
    return buf.getvalue()


def _styled_table(data: list[list[str]]) -> Table:
    t = Table(data, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16181E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8DBE2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F7F9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


CSV_COLUMNS = [
    "loan_id", "company_name", "hq_country", "loan_value", "loan_currency",
    "loan_value_eur", "asset_description", "asset_value", "coverage_ratio",
    "rule1_pass", "rule2_pass", "rule3_pass", "expected_currency",
    "overall_status", "resolution", "applied_fix_rule", "applied_fix_from",
    "applied_fix_to", "run_id", "fx_rate_date",
]


def stream_csv_rows(run_id: str):
    """Generator yielding CSV lines, one loan at a time - never materializes
    the full 100k-row result set in memory (Report.md section 4)."""
    conn = get_connection()
    fx_rate_date = conn.execute(
        "SELECT fx_rate_date FROM run_meta WHERE run_id = ?", (run_id,)
    ).fetchone()["fx_rate_date"]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    yield buf.getvalue()
    buf.seek(0); buf.truncate(0)

    cursor = conn.execute(
        """
        SELECT l.loan_id, l.company_name, l.hq_country, l.loan_value, l.loan_currency,
               l.asset_description, l.asset_value, l.overall_status,
               rr.loan_value_eur, rr.expected_currency, rr.coverage_ratio,
               rr.rule1_pass, rr.rule2_pass, rr.rule3_pass
        FROM loans l JOIN rule_results rr ON rr.loan_id = l.loan_id
        WHERE rr.run_id = ?
        ORDER BY l.loan_id
        """,
        (run_id,),
    )
    for row in cursor:
        applied = conn.execute(
            "SELECT rule_id, meta FROM audit_events "
            "WHERE run_id = ? AND loan_id = ? AND source = 'reviewer' "
            "AND message IN ('accepted_ai_fix','manual_fix') "
            "ORDER BY event_id DESC LIMIT 1",
            (run_id, row["loan_id"]),
        ).fetchone()
        fix_rule = fix_from = fix_to = ""
        resolution = "compliant" if (row["rule1_pass"] and row["rule2_pass"] and row["rule3_pass"]) else row["overall_status"]
        if applied and applied["meta"]:
            meta = json.loads(applied["meta"])
            fix_rule = meta.get("rule", "")
            fix_from = json.dumps(meta.get("from"))
            fix_to = json.dumps(meta.get("to"))
            resolution = "accepted_ai_fix" if row["overall_status"] == "compliant" else resolution

        writer.writerow([
            row["loan_id"], row["company_name"], row["hq_country"],
            row["loan_value"], row["loan_currency"], row["loan_value_eur"],
            row["asset_description"], row["asset_value"], row["coverage_ratio"],
            row["rule1_pass"], row["rule2_pass"], row["rule3_pass"],
            row["expected_currency"], row["overall_status"], resolution,
            fix_rule, fix_from, fix_to, run_id, fx_rate_date,
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)
