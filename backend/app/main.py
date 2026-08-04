"""
FastAPI app exposing the data the frontend (kyndryl-compliance-insights.jsx
being rebuilt in React) needs, one endpoint per tab. Read-only for now;
the /api/run endpoint triggers a fresh Engine 1 evaluation pass.

Run with:  uvicorn app.main:app --reload --port 8000
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json

import dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

dotenv.load_dotenv("../.env")

from agent import llm_client, review_actions
from app import queries, reports
from pipeline import run_evaluation
from pipeline.db import get_connection, init_db

app = FastAPI(title="BIL Loan Compliance API")


@app.on_event("startup")
def _ensure_schema():
    # CREATE TABLE IF NOT EXISTS is idempotent - safe to run on every start,
    # and picks up any schema additions made since the db file was created.
    init_db()


# Local dev: frontend (Vite, typically :5173) calls this API on a different
# port/origin. Tighten this to a specific origin before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=1)


def _resolve_run_id(conn, run_id: str | None) -> str:
    rid = run_id or queries.latest_completed_run_id(conn)
    if rid is None:
        raise HTTPException(404, "No completed run yet. POST /api/run first.")
    return rid


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/run")
def trigger_run():
    """Kick off a fresh Engine 1 evaluation pass. Blocks the request thread
    is avoided by running in a background thread; the caller polls
    /api/history for the new run's status."""
    future = _executor.submit(run_evaluation.run)

    def _log_errors(f):
        exc = f.exception()
        if exc:
            print(f"[app] run_evaluation failed: {exc}")

    future.add_done_callback(_log_errors)
    return {"status": "started"}


@app.get("/api/dashboard")
def dashboard(run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    summary = queries.run_summary(conn, rid)
    trend = queries.score_trend(conn)
    runs = queries.list_runs(conn, limit=5)

    total = summary["total_loans"]
    fails = {
        1: summary["rule1_fails"],
        2: summary["rule2_fails"],
        3: summary["rule3_fails"],
    }
    any_fail = fails[1] + fails[2] + fails[3]  # note: overlapping fails may double count; see /api/compliance for exact any-fail count
    exact_any_fail = conn.execute(
        "SELECT COUNT(*) AS n FROM rule_results WHERE run_id = ? "
        "AND NOT (rule1_pass = 1 AND rule2_pass = 1 AND rule3_pass = 1)",
        (rid,),
    ).fetchone()["n"]
    compliant = total - exact_any_fail

    return {
        "run_id": rid,
        "total": total,
        "fails": fails,
        "any_fail": exact_any_fail,
        "compliant": compliant,
        "pre_review_compliance": summary["pre_review_compliance"],
        "post_review_compliance": summary["post_review_compliance"],
        "removed": summary["removed"],
        "trend": [
            {"run_id": t["run_id"], "date": t["started_at"], "score": t["pre_review_compliance"]}
            for t in trend
        ],
        "recent_runs": [
            {
                "run_id": r["run_id"],
                "pre": r["pre_review_compliance"],
                "post": r["post_review_compliance"],
                "when": r["started_at"],
            }
            for r in runs
        ],
    }


@app.get("/api/compliance")
def compliance(run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    return {
        "run_id": rid,
        "rules": queries.rule_breakdown(conn, rid),
        "portfolio": queries.portfolio_by_company(conn),
    }


@app.get("/api/insights/fx-fragility")
def fx_fragility(run_id: str | None = None, band_pct: float = 5.0):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    return {"run_id": rid, **queries.fx_fragility(conn, rid, band_pct)}


@app.get("/api/review/groups")
def review_groups(run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    return {"run_id": rid, "groups": queries.review_groups(conn, rid)}


@app.get("/api/history")
def history():
    conn = get_connection()
    return {"runs": queries.list_runs(conn)}


@app.get("/api/history/{run_id}")
def history_detail(run_id: str):
    conn = get_connection()
    summary = queries.run_summary(conn, run_id)
    if summary is None:
        raise HTTPException(404, f"Run '{run_id}' not found.")
    return {"summary": summary, "audit_trail": queries.audit_trail(conn, run_id)}


# ---------- Review: paginated buckets + per-rule decisions ----------

@app.get("/api/review/loans")
def review_loans(bucket: int, run_id: str | None = None, limit: int = 50, offset: int = 0):
    if bucket not in (1, 2, 3):
        raise HTTPException(400, "bucket must be 1, 2, or 3")
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    return {"run_id": rid, **queries.bucket_loans(conn, rid, bucket, limit, offset)}


class Rule1Decision(BaseModel):
    decision: str  # "accept" | "ignore"


@app.post("/api/review/{loan_id}/rule1/decide")
def rule1_decide(loan_id: str, body: Rule1Decision, run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    try:
        return review_actions.decide_rule1(rid, loan_id, body.decision)
    except review_actions.ReviewError as exc:
        raise HTTPException(400, str(exc))


class Rule2Decision(BaseModel):
    decision: str  # "accept" | "manual" | "ignore"
    manual_currency: str | None = None


@app.post("/api/review/{loan_id}/rule2/decide")
def rule2_decide(loan_id: str, body: Rule2Decision, run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    try:
        return review_actions.decide_rule2(rid, loan_id, body.decision, body.manual_currency)
    except review_actions.ReviewError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/review/{loan_id}/rule3/generate")
def rule3_generate(loan_id: str, run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    try:
        return review_actions.generate_rule3_suggestion(rid, loan_id)
    except review_actions.ReviewError as exc:
        raise HTTPException(400, str(exc))


class Rule3Decision(BaseModel):
    decision: str  # "accept" | "manual" | "ignore"
    manual_asset: dict | None = None  # {"asset_description": ..., "asset_value": ...}


@app.post("/api/review/{loan_id}/rule3/decide")
def rule3_decide(loan_id: str, body: Rule3Decision, run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    try:
        return review_actions.decide_rule3(rid, loan_id, body.decision, body.manual_asset)
    except review_actions.ReviewError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/review/generate-wave1")
def generate_wave1(run_id: str | None = None, max_loans: int = 100):
    """Batch-generate Rule 3 suggestions for the settled Rule-3-only bucket
    (Action_Engine.md section 7, Wave 1). `max_loans` caps it for demo speed;
    remove the cap for a full production pass."""
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    bucket = queries.bucket_loans(conn, rid, 3, limit=max_loans, offset=0)
    generated = []
    for loan in bucket["loans"]:
        try:
            generated.append(review_actions.generate_rule3_suggestion(rid, loan["loan_id"]))
        except Exception as exc:  # noqa: BLE001 - report per-loan failures, don't abort the batch
            generated.append({"loan_id": loan["loan_id"], "error": str(exc)})
    return {"run_id": rid, "requested": len(bucket["loans"]), "generated": generated}


# ---------- Insights: FX-boundary fragility, with an on-demand AI narrative ----------

@app.post("/api/insights/fx-fragility/summary")
def fx_fragility_summary(run_id: str | None = None, band_pct: float = 5.0):
    """Button-triggered LLM call that ONLY narrates the deterministic tables
    below it (Insights-FX.md section 6) - it computes and predicts nothing."""
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    data = queries.fx_fragility(conn, rid, band_pct)

    above_sample = data["above"][:5]
    below_sample = data["below"][:5]
    prompt = (
        f"{data['total_above']} non-EUR loans currently pass Rule 1 but sit within "
        f"{band_pct}% of the EUR {data['floor_eur']:.0f} floor (fragile passes); "
        f"{data['total_below']} currently fail but by a thin margin (near-miss removals).\n\n"
        f"Fragile passes sample: {above_sample}\nNear-miss removals sample: {below_sample}\n\n"
        "Write a 2-3 sentence narrative: which loans are fragile, where exposure "
        "concentrates (by currency or company if the sample shows a pattern), and "
        "end with the caveat that this is a fragility signal on today's rates, not "
        "a prediction of where rates will move. Never say a loan 'will' pass or fail."
    )
    summary = llm_client.complete(
        [
            {"role": "system", "content": "You narrate deterministic financial risk tables. Never invent numbers not given to you. Never predict future rate movements."},
            {"role": "user", "content": prompt},
        ],
        # This is the one narrative/analysis surface in the app (as opposed to
        # the page assistant's short Q&A) - uses the larger chat model.
        model="gpt-5.4",
    )
    return {"run_id": rid, "summary": summary}


# ---------- Page assistant: grounded Q&A over each tab's live data ----------

class AssistantRequest(BaseModel):
    page: str  # "dashboard" | "compliance" | "insights" | "review" | "history"
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}], most recent last


def _assistant_context(conn, page: str, run_id: str | None) -> dict:
    """Pulls the same data the page itself renders, via the same query
    functions the REST endpoints use - the assistant never sees anything the
    reviewer couldn't also see on screen, and never computes its own numbers."""
    rid = _resolve_run_id(conn, run_id)
    if page == "dashboard":
        return {"run_summary": queries.run_summary(conn, rid), "recent_runs": queries.list_runs(conn, limit=5)}
    if page == "compliance":
        return {"rules": queries.rule_breakdown(conn, rid), "portfolio": queries.portfolio_by_company(conn)}
    if page == "insights":
        return queries.fx_fragility(conn, rid)
    if page == "review":
        return {"groups": queries.review_groups(conn, rid)}
    if page == "history":
        return {"runs": queries.list_runs(conn), "latest_audit_trail": queries.audit_trail(conn, rid)}
    return {"run_summary": queries.run_summary(conn, rid)}


@app.post("/api/assistant")
def assistant(body: AssistantRequest, run_id: str | None = None):
    conn = get_connection()
    context = _assistant_context(conn, body.page, run_id)

    system = (
        "You are the page assistant embedded in a loan-compliance review tool. "
        "Explain what's shown on the current page and answer questions about it. "
        "Ground every claim ONLY in the JSON context below - never invent a number, "
        "a loan, or a company that isn't in it. If the context doesn't contain the "
        "answer, say so plainly instead of guessing. Keep replies to 2-4 sentences "
        "unless the question needs a list.\n\n"
        f"Current page: {body.page}\nContext JSON:\n{json.dumps(context, default=str)}"
    )
    messages = [{"role": "system", "content": system}, *body.history, {"role": "user", "content": body.message}]
    reply = llm_client.complete(messages, model="gpt-5.4-mini", max_completion_tokens=300)
    return {"reply": reply}


# ---------- Reports: PDF (aggregates) + CSV (row-level), per run ----------

@app.get("/api/reports/{run_id}/pdf")
def report_pdf(run_id: str):
    try:
        pdf_bytes = reports.generate_pdf(run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="compliance-report-{run_id}.pdf"'},
    )


@app.get("/api/reports/{run_id}/csv")
def report_csv(run_id: str):
    return StreamingResponse(
        reports.stream_csv_rows(run_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="loan-detail-{run_id}.csv"'},
    )
