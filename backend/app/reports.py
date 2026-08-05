"""
Report generation. See DOCS/REPORT_GENERATION_SPEC.md for the full PDF layout
this implements (colors, sections, section order). Two formats, two
audiences:
- PDF: aggregates only (run_meta + GROUP BY queries), never renders all
  100,000 rows.
- CSV: one row per loan, streamed from the loans/rule_results/audit_events
  join, never pre-aggregated and never loaded fully into memory first.

Both are generated per run_id, so a past run can still be re-exported.
"""

import csv
import io
import json
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pipeline.db import get_connection
from app.queries import any_fail_count, post_review_compliance as _post_review_compliance

# Palette + rule labels shared by every table/callout in the PDF
# (REPORT_GENERATION_SPEC.md section 3).
COLORS = {
    "primary": "#1a1a1a",
    "secondary": "#6b6b6b",
    "muted": "#999999",
    "rule1": "#D93025", "rule1_bg": "#FDE8E8",
    "rule2": "#E37400", "rule2_bg": "#FFF3E0",
    "rule3": "#1A73E8", "rule3_bg": "#E8F0FE",
    "success": "#0D652D", "success_bg": "#E6F4EA",
    "danger_bg": "#FDE8E8", "danger_text": "#D93025",
    "info_bg": "#E8F0FE", "info_text": "#1A73E8",
    "border": "#E0E0E0",
    "bar_bg": "#F0F0F0",
    "header_bg": "#16181E",
}
RULE_NAMES = {1: "Minimum loan value (EUR 25k)", 2: "Currency matches HQ", 3: "Asset coverage"}
RULE_COLOR_KEYS = {1: "rule1", 2: "rule2", 3: "rule3"}


def format_eur(value) -> str:
    """€1.42B / €118.7M / €25.0K / €900 (REPORT_GENERATION_SPEC.md section 3) -
    abbreviated so exposure figures stay scannable next to loan/company counts."""
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}\u20ac{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}\u20ac{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}\u20ac{value / 1_000:.1f}K"
    return f"{sign}\u20ac{value:,.0f}"


def _human_date(ts: str | None) -> str:
    if not ts:
        return "n/a"
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        return f"{dt.day} {dt.strftime('%B')} {dt.year}"
    except ValueError:
        return ts


def _duration_text(started_at: str | None, completed_at: str | None) -> str:
    if not started_at or not completed_at:
        return "n/a (run in progress)"
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        start = datetime.strptime(started_at[:19], fmt)
        end = datetime.strptime(completed_at[:19], fmt)
        seconds = max(int((end - start).total_seconds()), 0)
        return f"{seconds}s" if seconds < 120 else f"{seconds // 60}m {seconds % 60}s"
    except ValueError:
        return "n/a"


# ---------- small drawing helpers (pills, bars, callouts) ----------

def _hr(width: float) -> Table:
    t = Table([[""]], colWidths=[width], rowHeights=[2])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.75, colors.HexColor(COLORS["border"]))]))
    return t


def _badge(text: str, bg_hex: str, fg_hex: str) -> Table:
    """A tight-fitting colored pill. Uses a plain string cell (not a
    Paragraph) so the table hugs the text instead of expanding to fill
    whatever width it's given - the usual ReportLab pitfall for 'pill' UI."""
    t = Table([[text]], colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor(fg_hex)),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _rule_pill(rule_num: int) -> Table:
    key = RULE_COLOR_KEYS[rule_num]
    return _badge(f"R{rule_num}", COLORS[f"{key}_bg"], COLORS[key])


def _callout(text: str, bg_hex: str, fg_hex: str, content_width: float) -> Table:
    style = ParagraphStyle("Callout", fontSize=10.5, leading=15, textColor=colors.HexColor(fg_hex))
    t = Table([[Paragraph(text, style)]], colWidths=[content_width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    return t


def _mini_bar(pct: float, color_key: str, max_width: float = 70, height: float = 7) -> Table:
    pct = max(0.0, min(100.0, pct))
    fill_w = max(round(max_width * pct / 100, 2), 0.6)
    bg_w = max(max_width - fill_w, 0.6)
    t = Table([["", ""]], colWidths=[fill_w, bg_w], rowHeights=[height])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(COLORS[color_key])),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(COLORS["bar_bg"])),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _metric_cards(items: list[tuple[str, str, str, str]], content_width: float) -> Table:
    """items: (big_text, label_text, bg_hex, fg_hex) - the 3 boxes above the
    overlap table (REPORT_GENERATION_SPEC.md section 1.5)."""
    gap = 10
    w = (content_width - gap * (len(items) - 1)) / len(items)
    big_style = ParagraphStyle("CardBig", fontSize=20, leading=24, fontName="Helvetica-Bold")
    label_style = ParagraphStyle("CardLabel", fontSize=10, leading=13)
    row, widths = [], []
    for i, (big, label, bg, fg) in enumerate(items):
        cell = Table(
            [[Paragraph(big, ParagraphStyle("b", parent=big_style, textColor=colors.HexColor(fg)))],
             [Paragraph(label, ParagraphStyle("l", parent=label_style, textColor=colors.HexColor(fg)))]],
            colWidths=[w],
        )
        cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
            ("TOPPADDING", (0, 0), (-1, 0), 10), ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
            ("TOPPADDING", (0, 1), (-1, 1), 0), ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        row.append(cell)
        widths.append(w)
        if i < len(items) - 1:
            row.append("")
            widths.append(gap)
    outer = Table([row], colWidths=widths)
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def _h2(styles) -> ParagraphStyle:
    return ParagraphStyle("H2", parent=styles["Heading2"], fontSize=16, textColor=colors.HexColor(COLORS["primary"]))


# ---------- data gathering ----------

def _rule_eur_exposure(conn, run_id: str) -> dict[int, float]:
    """SUM(loan_value_eur) for loans currently failing each rule - only
    available from the live rule_results table (no static aggregate is
    stamped for this at evaluation time)."""
    result = {}
    for rule in (1, 2, 3):
        row = conn.execute(
            f"SELECT SUM(CAST(loan_value_eur AS REAL)) AS eur FROM rule_results "
            f"WHERE run_id = ? AND rule{rule}_pass = 0",
            (run_id,),
        ).fetchone()
        result[rule] = row["eur"] or 0.0
    return result


def _overlap_breakdown(conn, run_id: str) -> dict:
    """Groups currently-failing loans by their exact pass/fail combination
    (REPORT_GENERATION_SPEC.md section 1.5) - this is why rule totals can
    exceed the unique failing-loan count: a loan failing 2 rules is counted
    once here but twice in the per-rule totals."""
    rows = conn.execute(
        """
        SELECT rule1_pass, rule2_pass, rule3_pass, COUNT(*) AS cnt
        FROM rule_results
        WHERE run_id = ? AND NOT (rule1_pass = 1 AND rule2_pass = 1 AND rule3_pass = 1)
        GROUP BY rule1_pass, rule2_pass, rule3_pass
        ORDER BY cnt DESC
        """,
        (run_id,),
    ).fetchall()
    combos = []
    single_only = exactly_two = all_three = 0
    for r in rows:
        failed_rules = [n for n, p in ((1, r["rule1_pass"]), (2, r["rule2_pass"]), (3, r["rule3_pass"])) if not p]
        label = "+".join(f"R{n}" for n in failed_rules)
        combos.append({"label": f"{label} only" if len(failed_rules) == 1 else label, "count": r["cnt"]})
        if len(failed_rules) == 1:
            single_only += r["cnt"]
        elif len(failed_rules) == 2:
            exactly_two += r["cnt"]
        else:
            all_three += r["cnt"]
    return {"combos": combos, "single_only": single_only, "exactly_two": exactly_two, "all_three": all_three}


def _disposition_and_unresolved(conn, run_id: str) -> tuple[dict, list]:
    """Per-disposition-bucket [count, EUR exposure]. Counts come from
    audit_events (source='reviewer') - the durable record of what a human
    decided - because accepting a fix REWRITES rule_results to the new,
    now-passing verdict (Action_Engine.md section 10), so 'still failing in
    rule_results' alone can't recover which loans were fixed. Unresolved =
    currently failing AND never touched by any reviewer decision."""
    rows = conn.execute(
        """
        SELECT ae.loan_id, ae.message, rr.loan_value_eur
        FROM audit_events ae
        LEFT JOIN rule_results rr ON rr.loan_id = ae.loan_id AND rr.run_id = ae.run_id
        WHERE ae.run_id = ? AND ae.source = 'reviewer'
          AND ae.message IN ('manual_fix', 'accepted_ai_fix', 'ignored', 'removed')
        """,
        (run_id,),
    ).fetchall()

    key_by_message = {
        "manual_fix": "fixed_manual", "accepted_ai_fix": "fixed_ai",
        "ignored": "ignored", "removed": "removed",
    }
    disposition = {k: [0, 0.0] for k in ("fixed_manual", "fixed_ai", "ignored", "removed")}
    touched_loan_ids = set()
    for r in rows:
        bucket = key_by_message.get(r["message"])
        if bucket is None:
            continue
        touched_loan_ids.add(r["loan_id"])
        disposition[bucket][0] += 1
        disposition[bucket][1] += float(r["loan_value_eur"] or 0)

    fail_rows = conn.execute(
        """
        SELECT loan_id, loan_value_eur FROM rule_results
        WHERE run_id = ? AND NOT (rule1_pass = 1 AND rule2_pass = 1 AND rule3_pass = 1)
        """,
        (run_id,),
    ).fetchall()
    unresolved_n, unresolved_eur = 0, 0.0
    for r in fail_rows:
        if r["loan_id"] in touched_loan_ids:
            continue
        unresolved_n += 1
        unresolved_eur += float(r["loan_value_eur"] or 0)

    return disposition, [unresolved_n, unresolved_eur]


# ---- FIX #3: _rescue_note now counts ACTUAL rescues from audit events ----
# Old formula: rescued = raw_rule1_fails - removed
#   This was wrong because it assumed every R1 failure not removed was "rescued",
#   but most R1-only failures (9,208 loans) have the CORRECT currency and can
#   never be rescued — they're genuinely below EUR 25k.
#   It also broke pre-review (removed=0 → claimed all 11,314 were rescued).
#
# New formula: count loans that (a) had a Rule 2 currency fix accepted,
#   AND (b) now pass Rule 1 in rule_results after the re-check.
#   Pre-review this correctly returns 0.

def _rescue_note(conn, run_id: str, removed: int) -> str:
    """'X failed Rule 1 at evaluation; Y were rescued by a currency fix and
    re-check; Z were genuinely removed.' (Report.md 2.4) - only rendered by
    the caller if removed > 0 (REPORT_GENERATION_SPEC.md section 2.1)."""
    row = conn.execute("SELECT rule1_fails FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    raw_rule1_fails = row["rule1_fails"] if row else 0

    # Count actual rescues: loans where a reviewer accepted/applied a Rule 2
    # currency fix, and that loan NOW passes Rule 1 after the OPA re-check.
    rescued_row = conn.execute(
        """
        SELECT COUNT(DISTINCT ae.loan_id) AS n
        FROM audit_events ae
        JOIN rule_results rr ON rr.loan_id = ae.loan_id AND rr.run_id = ae.run_id
        WHERE ae.run_id = ?
          AND ae.source = 'reviewer'
          AND ae.message IN ('accepted_ai_fix', 'manual_fix')
          AND (
              json_extract(ae.meta, '$.rule') = 2
              OR json_extract(ae.meta, '$.rule') = '2'
          )
          AND rr.rule1_pass = 1
        """,
        (run_id,),
    ).fetchone()
    rescued = rescued_row["n"] if rescued_row else 0

    return (
        f"{raw_rule1_fails} failed Rule 1 at evaluation; {rescued} were rescued "
        f"by a currency fix and re-check; {removed} were genuinely removed."
    )


# ---- Also add potential_rescue_note for pre-review state ----

def _potential_rescue_note(conn, run_id: str) -> str:
    """Before any review actions, show how many loans COULD be rescued
    (i.e. fail both R1 and R2 — fixing currency might flip R1)."""
    row = conn.execute("SELECT rule1_fails FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    raw_rule1_fails = row["rule1_fails"] if row else 0

    potential = conn.execute(
        """
        SELECT COUNT(*) AS n FROM rule_results
        WHERE run_id = ? AND rule1_pass = 0 AND rule2_pass = 0
        """,
        (run_id,),
    ).fetchone()["n"]

    r1_only = raw_rule1_fails - potential
    return (
        f"{raw_rule1_fails} loans fail Rule 1. Of these, {potential} also fail Rule 2 "
        f"and may be rescued by a currency fix; {r1_only} have the correct currency "
        f"and are genuinely below EUR 25,000."
    )


def _portfolio_eur(conn, run_id: str, top_n: int = 10) -> tuple[list[dict], dict]:
    """Top-N companies by EUR exposure (normalized via loan_value_eur, never
    raw mixed-currency loan_value), plus a grand total across ALL companies
    for the footer row (REPORT_GENERATION_SPEC.md section 2.2)."""
    rows = conn.execute(
        """
        SELECT l.company_name, l.hq_country, COUNT(*) AS n_loans,
               SUM(CAST(rr.loan_value_eur AS REAL)) AS total_eur,
               SUM(CASE WHEN NOT (rr.rule1_pass = 1 AND rr.rule2_pass = 1 AND rr.rule3_pass = 1)
                   THEN 1 ELSE 0 END) AS failures
        FROM loans l
        JOIN rule_results rr ON rr.loan_id = l.loan_id AND rr.run_id = ?
        GROUP BY l.company_name, l.hq_country
        ORDER BY total_eur DESC
        LIMIT ?
        """,
        (run_id, top_n),
    ).fetchall()
    grand = conn.execute(
        """
        SELECT COUNT(*) AS n_loans,
               SUM(CAST(rr.loan_value_eur AS REAL)) AS total_eur,
               SUM(CASE WHEN NOT (rr.rule1_pass = 1 AND rr.rule2_pass = 1 AND rr.rule3_pass = 1)
                   THEN 1 ELSE 0 END) AS failures
        FROM loans l JOIN rule_results rr ON rr.loan_id = l.loan_id AND rr.run_id = ?
        """,
        (run_id,),
    ).fetchone()
    return [dict(r) for r in rows], dict(grand)


def build_report_data(run_id: str) -> dict:
    conn = get_connection()
    run_meta = conn.execute("SELECT * FROM run_meta WHERE run_id = ?", (run_id,)).fetchone()
    if run_meta is None:
        raise ValueError(f"Run '{run_id}' not found")
    run_meta = dict(run_meta)
    total = run_meta["total_loans"]

    # unique_failing_loans is LIVE (current rule_results state); rule_totals
    # is the FROZEN per-rule sum stamped at evaluation - matching the
    # Compliance tab's rule_breakdown. The two can diverge once fixes land
    # (a fixed loan drops out of "currently failing" but its original
    # evaluation-time fail is still counted in rule_totals) - that gap IS
    # the overlap-plus-resolved story the callout explains.
    unique_failing = any_fail_count(conn, run_id)
    rule_totals = run_meta["rule1_fails"] + run_meta["rule2_fails"] + run_meta["rule3_fails"]
    overlap_count = max(rule_totals - unique_failing, 0)

    eur_exposure = _rule_eur_exposure(conn, run_id)
    rules = [
        {
            "rule": rule,
            "name": RULE_NAMES[rule],
            "failed": run_meta[f"rule{rule}_fails"],
            "eur_exposure": eur_exposure[rule],
            "fail_pct": round(100 * run_meta[f"rule{rule}_fails"] / total, 2) if total else 0.0,
        }
        for rule in (1, 2, 3)
    ]

    disposition, unresolved = _disposition_and_unresolved(conn, run_id)
    disposition["unresolved"] = unresolved

    portfolio_rows, portfolio_grand_total = _portfolio_eur(conn, run_id)

    # Determine which rescue note to use
    total_reviewed = sum(disposition[k][0] for k in ("fixed_manual", "fixed_ai", "ignored", "removed"))
    removed_count = disposition["removed"][0]

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
        "unique_failing_loans": unique_failing,
        "rule_totals": rule_totals,
        "overlap_count": overlap_count,
        "rules": rules,
        "overlap": _overlap_breakdown(conn, run_id),
        "disposition": disposition,
        "total_reviewed": total_reviewed,
        # FIX: use actual rescue note (counts real rescues) when removals exist,
        # potential rescue note (counts R1+R2 overlap) pre-review
        "rescue_note": _rescue_note(conn, run_id, removed_count),
        "potential_rescue_note": _potential_rescue_note(conn, run_id),
        "portfolio": portfolio_rows,
        "portfolio_grand_total": portfolio_grand_total,
    }


# ---------- page 1 sections ----------

def _header_section(data: dict, content_width: float) -> list:
    title_style = ParagraphStyle("ReportTitle", fontSize=24, leading=28, fontName="Helvetica-Bold", textColor=colors.HexColor(COLORS["primary"]))
    subtitle_style = ParagraphStyle("ReportSubtitle", fontSize=12, leading=15, textColor=colors.HexColor(COLORS["secondary"]))
    date_style = ParagraphStyle("ReportDate", fontSize=12, leading=15, alignment=TA_RIGHT, textColor=colors.HexColor(COLORS["primary"]))
    runid_style = ParagraphStyle("ReportRunId", fontSize=10, leading=13, alignment=TA_RIGHT, fontName="Courier", textColor=colors.HexColor(COLORS["secondary"]))

    left = [Paragraph("Loan compliance report", title_style), Paragraph("Kyndryl \u2014 Secured loan portfolio review", subtitle_style)]
    right = [Paragraph(_human_date(data["started_at"]), date_style), Paragraph(f"Run {data['run_id']}", runid_style)]

    t = Table([[left, right]], colWidths=[content_width * 0.6, content_width * 0.4])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [t, Spacer(1, 6), _hr(content_width), Spacer(1, 16)]


def _headline_section(data: dict, content_width: float) -> list:
    label_style = ParagraphStyle("HLabel", fontSize=11, textColor=colors.HexColor(COLORS["secondary"]))
    big_style = ParagraphStyle("HBig", fontSize=48, leading=52, fontName="Helvetica-Bold", textColor=colors.HexColor(COLORS["primary"]))
    med_style = ParagraphStyle("HMed", fontSize=28, leading=32, fontName="Helvetica-Bold", textColor=colors.HexColor(COLORS["primary"]))
    sub_style = ParagraphStyle("HSub", fontSize=12, textColor=colors.HexColor(COLORS["secondary"]))

    pre, post = data["pre_review_compliance"], data["post_review_compliance"]
    left = [
        Paragraph("Compliance score (pre-review)", label_style),
        Paragraph(f"{pre:.2f}%" if pre is not None else "n/a", big_style),
        Spacer(1, 4),
        Paragraph(f"{data['unique_failing_loans']:,} of {data['total_loans']:,} loans have failures", sub_style),
    ]

    delta = (post - pre) if (pre is not None and post is not None) else None
    if delta is None:
        badge_text, badge_bg, badge_fg = "n/a", COLORS["bar_bg"], COLORS["secondary"]
    elif delta > 0:
        badge_text, badge_bg, badge_fg = f"+{delta:.2f} pts", COLORS["success_bg"], COLORS["success"]
    elif delta == 0:
        badge_text, badge_bg, badge_fg = "+0.00 pts", COLORS["bar_bg"], COLORS["secondary"]
    else:
        badge_text, badge_bg, badge_fg = f"{delta:.2f} pts", COLORS["danger_bg"], COLORS["danger_text"]

    right = [
        Paragraph("Post-review", label_style),
        Paragraph(f"{post:.2f}%" if post is not None else "n/a", med_style),
        Spacer(1, 4),
        _badge(badge_text, badge_bg, badge_fg),
    ]

    t = Table([[left, right]], colWidths=[content_width * 0.6, content_width * 0.4])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [t, Spacer(1, 20)]


def _rule_table(data: dict, content_width: float) -> Table:
    rows = [["Rule", "Name", "Failed", "EUR exposure", "Fail %", ""]]
    for r in data["rules"]:
        rows.append([
            _rule_pill(r["rule"]), r["name"], f"{r['failed']:,}",
            format_eur(r["eur_exposure"]), f"{r['fail_pct']:.2f}%",
            _mini_bar(r["fail_pct"] * 6, RULE_COLOR_KEYS[r["rule"]]),  # *6 so a ~15% fail rate still reads visually
        ])
    col_widths = [content_width * 0.08, content_width * 0.30, content_width * 0.13,
                  content_width * 0.17, content_width * 0.12, content_width * 0.20]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(COLORS["secondary"])),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor(COLORS["border"])),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, colors.HexColor(COLORS["border"])),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _disposition_table(disposition: dict) -> Table:
    rows = [["Disposition", "Count", "EUR value"]]
    for label, key in [
        ("Fixed manually", "fixed_manual"), ("Fixed via AI suggestion", "fixed_ai"),
        ("Ignored", "ignored"), ("Removed (Rule 1)", "removed"),
    ]:
        n, eur = disposition[key]
        rows.append([label, f"{n:,}", format_eur(eur)])
    n, eur = disposition["unresolved"]
    rows.append(["Unresolved", f"{n:,}", format_eur(eur)])

    t = Table(rows, colWidths=[None, None, None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLORS["header_bg"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS["border"])),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(COLORS["bar_bg"])),
    ]))
    return t


def _portfolio_table(portfolio_rows: list[dict], grand_total: dict) -> Table:
    rows = [["Company", "HQ", "Loans", "Total (EUR)", "Failures"]]
    fail_row_indices = []
    for i, p in enumerate(portfolio_rows, start=1):
        rows.append([p["company_name"], p["hq_country"], f"{p['n_loans']:,}",
                     format_eur(p["total_eur"]), f"{p['failures']:,}"])
        if p["failures"] > 0:
            fail_row_indices.append(i)
    grand_idx = len(rows)
    rows.append(["Grand total", "", f"{grand_total['n_loans']:,}",
                 format_eur(grand_total["total_eur"]), f"{grand_total['failures']:,}"])

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLORS["header_bg"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS["border"])),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTNAME", (0, grand_idx), (-1, grand_idx), "Helvetica-Bold"),
        ("BACKGROUND", (0, grand_idx), (-1, grand_idx), colors.HexColor(COLORS["bar_bg"])),
    ]
    for i in fail_row_indices:
        style_cmds.append(("TEXTCOLOR", (4, i), (4, i), colors.HexColor(COLORS["rule1"])))
    t = Table(rows, colWidths=[None] * 5)
    t.setStyle(TableStyle(style_cmds))
    return t


def _methodology_paragraph(data: dict) -> Paragraph:
    duration = _duration_text(data["started_at"], data["completed_at"])
    fx_status = (
        "Stale cache (flagged)" if data["fx_stale"]
        else ("Primary source (Frankfurter)" if data["fx_source"] == "frankfurter" else "Secondary source (exchangerate.host)")
    )
    text = (
        "<b>Methodology</b><br/>"
        "Rule engine: OPA / Rego, package 'compliance'.<br/>"
        "Country-to-currency table: static, hand-built (8 currencies, 18 countries).<br/>"
        f"FX source: Frankfurter API (ECB rates), dated {data['fx_rate_date'] or 'n/a'}.<br/>"
        "FX fallback: exchangerate.host (secondary); last cached rate flagged stale if both unavailable.<br/>"
        f"FX status this run: {fx_status}.<br/>"
        f"Run duration: {data['started_at']} to {data['completed_at'] or 'in progress'} ({duration})."
    )
    style = ParagraphStyle("Methodology", fontSize=9, leading=13, textColor=colors.HexColor(COLORS["muted"]))
    return Paragraph(text, style)


def generate_pdf(run_id: str) -> bytes:
    data = build_report_data(run_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=50, rightMargin=50, topMargin=40, bottomMargin=40,
        title=f"Loan compliance report - {run_id}",
    )
    content_width = doc.width
    styles = getSampleStyleSheet()
    story = []

    # ---- Page 1: header, headline score, per-rule breakdown, overlap ----
    story += _header_section(data, content_width)
    story += _headline_section(data, content_width)

    story.append(Paragraph("Per-rule breakdown", _h2(styles)))
    story.append(Spacer(1, 8))
    story.append(_rule_table(data, content_width))
    story.append(Spacer(1, 16))

    overlap_text = (
        f"Rule totals ({data['rule_totals']:,}) exceed unique failing loans ({data['unique_failing_loans']:,}) "
        f"because {data['overlap_count']:,} loans fail multiple rules (or were already fixed and dropped out of "
        "the live count). See overlap table below."
        if data["overlap_count"] > 0 else
        f"Rule totals ({data['rule_totals']:,}) match unique failing loans ({data['unique_failing_loans']:,}) - "
        "no loan in this run fails more than one rule."
    )
    story.append(_callout(overlap_text, COLORS["info_bg"], COLORS["info_text"], content_width))
    story.append(Spacer(1, 18))

    story.append(Paragraph("Rule overlap", _h2(styles)))
    story.append(Spacer(1, 10))
    story.append(_metric_cards([
        (f"{data['overlap']['single_only']:,}", "Single rule only", COLORS["bar_bg"], COLORS["primary"]),
        (f"{data['overlap']['exactly_two']:,}", "Exactly 2 rules", COLORS["rule2_bg"], COLORS["rule2"]),
        (f"{data['overlap']['all_three']:,}", "All 3 rules", COLORS["danger_bg"], COLORS["rule1"]),
    ], content_width))
    story.append(Spacer(1, 14))
    story.append(_styled_table(
        [["Combination", "Count"]] + [[c["label"], f"{c['count']:,}"] for c in data["overlap"]["combos"]]
    ))

    story.append(PageBreak())

    # ---- Page 2: disposition, portfolio, methodology ----
    total_reviewed = data["total_reviewed"]
    if total_reviewed == 0:
        story.append(_callout(
            f"No review actions have been taken yet. All {data['disposition']['unresolved'][0]:,} failures are unresolved.",
            COLORS["danger_bg"], COLORS["danger_text"], content_width,
        ))
        story.append(Spacer(1, 12))
        # FIX: Show potential rescue note pre-review instead of the broken formula
        rescue_style = ParagraphStyle("Rescue", fontSize=10, leading=14, textColor=colors.HexColor(COLORS["secondary"]), fontName="Helvetica-Oblique")
        story.append(Paragraph(data["potential_rescue_note"], rescue_style))
        story.append(Spacer(1, 16))

    story.append(Paragraph("Disposition summary", _h2(styles)))
    story.append(Spacer(1, 8))
    story.append(_disposition_table(data["disposition"]))
    story.append(Spacer(1, 10))

    # FIX: Only show rescue note post-review when removals have actually happened
    if total_reviewed > 0 and data["disposition"]["removed"][0] > 0:
        rescue_style = ParagraphStyle("Rescue", fontSize=10, leading=14, textColor=colors.HexColor(COLORS["secondary"]), fontName="Helvetica-Oblique")
        story.append(Paragraph(data["rescue_note"], rescue_style))
        story.append(Spacer(1, 16))

    story.append(Paragraph("Portfolio summary \u2014 top 10 by EUR exposure", _h2(styles)))
    story.append(Spacer(1, 8))
    story.append(_portfolio_table(data["portfolio"], data["portfolio_grand_total"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Showing top 10. Full table in CSV export. All values converted to EUR at run-date FX rate.",
        ParagraphStyle("Footnote", fontSize=9, textColor=colors.HexColor(COLORS["muted"])),
    ))
    story.append(Spacer(1, 22))
    story.append(_hr(content_width))
    story.append(Spacer(1, 10))
    story.append(_methodology_paragraph(data))

    doc.build(story)
    return buf.getvalue()


def _styled_table(data: list[list[str]]) -> Table:
    t = Table(data, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLORS["header_bg"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(COLORS["border"])),
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