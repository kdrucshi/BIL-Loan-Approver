"""
FastAPI app exposing the data the frontend (kyndryl-compliance-insights.jsx
being rebuilt in React) needs, one endpoint per tab. Read-only for now;
the /api/run endpoint triggers a fresh Engine 1 evaluation pass.

Run with:  uvicorn app.main:app --reload --port 8000
"""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import re

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
    # queries.any_fail_count is the exact (non-overlapping) any-fail count -
    # shared with the page assistant's dashboard context so the two never drift.
    exact_any_fail = queries.any_fail_count(conn, rid)
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


# ---- FIX: /api/compliance now passes run_id to portfolio_by_company ----
@app.get("/api/compliance")
def compliance(run_id: str | None = None):
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    return {
        "run_id": rid,
        "rules": queries.rule_breakdown(conn, rid),
        "portfolio": queries.portfolio_by_company(conn, rid),
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


class BulkDecision(BaseModel):
    decision: str  # "accept" | "ignore"
    max_loans: int | None = None  # optional cap - mainly useful for a Rule 3 "accept" (LLM call per loan)


@app.post("/api/review/groups/{group_id}/bulk-decide")
def review_bulk_decide(group_id: str, body: BulkDecision, run_id: str | None = None):
    """Applies accept/ignore to EVERY loan currently in a review group in one
    call. This is what the Review tab's 'Accept all' / 'Ignore all' buttons
    call now - they previously only updated local UI state and never
    reached the backend, so nothing was actually fixed, re-checked, or
    reflected in the dashboard."""
    conn = get_connection()
    rid = _resolve_run_id(conn, run_id)
    try:
        return review_actions.bulk_decide_group(rid, group_id, body.decision, body.max_loans)
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
        # Short grounded narration, same model tier as the page assistant -
        # see the MODEL_CHAT / MODEL_ORCHESTRATOR comment in llm_client.py.
        model=llm_client.MODEL_CHAT,
    )
    return {"run_id": rid, "summary": summary}


# ---------- Page assistant: grounded Q&A over each tab's live data ----------

class AssistantRequest(BaseModel):
    page: str  # "dashboard" | "compliance" | "insights" | "review" | "history"
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}], most recent last


# Loan IDs are "L" + digits (e.g. L000012, see loans.csv/companies.json).
# Letting the reviewer just type a loan number into the chat is friendlier
# than adding a separate lookup field, and detecting it here keeps the
# frontend page-agnostic - it just forwards whatever the user typed.
_LOAN_ID_RE = re.compile(r"\bl\d{5,}\b", re.IGNORECASE)


def _extract_loan_id(message: str) -> str | None:
    match = _LOAN_ID_RE.search(message)
    return match.group(0).upper() if match else None


def _assistant_context(conn, page: str, run_id: str | None, message: str = "") -> dict:
    """Pulls the same data the page itself renders, via the same query
    functions the REST endpoints use - the assistant never sees anything the
    reviewer couldn't also see on screen, and never computes its own numbers."""
    rid = _resolve_run_id(conn, run_id)
    if page == "dashboard":
        summary = queries.run_summary(conn, rid)
        any_fail = queries.any_fail_count(conn, rid)
        context = {
            "run_summary": summary,
            # Exact counts matching what the Dashboard hero/rule cards show -
            # not the raw per-rule sums, which can double-count a loan that
            # fails more than one rule.
            "loans_passing_all_rules_now": summary["total_loans"] - any_fail,
            "loans_failing_at_least_one_rule_now": any_fail,
            # Precedence-aware (Rule 2 -> Rule 1 -> Rule 3), matches the
            # Review tab exactly - "how many are pending human review".
            "pending_human_review_by_rule": queries.pending_by_rule(conn, rid),
            "recent_runs": queries.list_runs(conn, limit=5),
        }
        loan_id = _extract_loan_id(message)
        if loan_id:
            detail = queries.loan_detail(conn, rid, loan_id)
            context["loan_lookup"] = detail if detail is not None else {"found": False, "loan_id": loan_id}
        return context
    if page == "compliance":
        # FIX: pass run_id to portfolio_by_company
        return {"rules": queries.rule_breakdown(conn, rid), "portfolio": queries.portfolio_by_company(conn, rid)}
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
    context = _assistant_context(conn, body.page, run_id, body.message)

    system = (
        "You are the page assistant embedded in a loan-compliance review tool. "
        "Respond naturally and briefly to greetings, thanks, and small talk - those "
        "don't need to be grounded in data. For any factual claim about loans, "
        "counts, rules, or figures, ground it ONLY in the JSON context below - never "
        "invent a number, a loan, or a company that isn't in it. If the context "
        "doesn't contain the answer to a data question, say so plainly instead of "
        "guessing.\n\n"
        "If the context includes a 'loan_lookup' entry (the reviewer asked about a "
        "specific loan), explain it clearly using this EXACT format:\n\n"
        "1. State the loan basics: company, loan_value, loan_currency, asset, asset_value.\n"
        "2. For EACH rule, start the sentence with the verdict word from the context "
        "(rule1_verdict, rule2_verdict, rule3_verdict - these say PASS or FAIL). "
        "Use this pattern:\n"
        "   - 'Rule 1: FAIL. The EUR value is X, which is below the EUR 25,000 threshold.'\n"
        "   - 'Rule 1: PASS. The EUR value is X, which is above EUR 25,000.'\n"
        "   - 'Rule 2: FAIL. The loan is in X but should be Y (company HQ is in Z).'\n"
        "   - 'Rule 2: PASS. The currency X matches the expected currency.'\n"
        "   - 'Rule 3: FAIL. Coverage ratio is X, which is below 0.5 (50%).'\n"
        "   - 'Rule 3: PASS. Coverage ratio is X, which is above 0.5 (50%).'\n"
        "CRITICAL: Never say 'passes' then 'fails' in the same sentence. Use the "
        "verdict field directly — if rule1_verdict says FAIL, the rule FAILED, period.\n"
        "3. Mention any 'suggestions' entries (these are the recommended fix).\n"
        "4. If 'loan_lookup' shows found: false, say the loan isn't in the current run.\n\n"
        "Keep replies to 2-4 sentences unless the question needs a list.\n\n"
        f"Current page: {body.page}\nContext JSON:\n{json.dumps(context, default=str)}"
    )
    messages = [{"role": "system", "content": system}, *body.history, {"role": "user", "content": body.message}]
    reply = llm_client.complete(messages, model=llm_client.MODEL_CHAT, max_completion_tokens=300)
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