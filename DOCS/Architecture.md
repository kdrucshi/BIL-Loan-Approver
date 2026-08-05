# BIL Loan Approver — Architecture Overview

Full architecture traced from the code (frontend → API → pipeline/agent → DB/OPA).

```mermaid
flowchart TB
    subgraph FE["Frontend — React + Vite (:5173)"]
        direction TB
        Dashboard["Dashboard tab<br/>compliance %, trend, rule fail counts"]
        Review["Review tab<br/>grouped fixes, accept/ignore/manual, bulk actions"]
        Insights["Insights tab<br/>FX-boundary fragility + AI summary"]
        Compliance["Compliance tab<br/>rule breakdown, portfolio by company"]
        History["History tab<br/>past runs, audit trail"]
        Assistant["Page assistant chat<br/>(all tabs)"]
    end

    subgraph API["FastAPI backend — app/main.py (:8000)"]
        direction TB
        R1["/api/run (POST)<br/>triggers Engine 1 pass"]
        R2["/api/dashboard, /api/compliance,<br/>/api/insights/fx-fragility"]
        R3["/api/review/* <br/>loans, decide, bulk-decide, generate"]
        R4["/api/history, /api/history/:id"]
        R5["/api/assistant (POST)"]
        R6["/api/reports/:run_id/pdf, /csv"]
    end

    subgraph LOGIC["Query + business logic"]
        Queries["app/queries.py<br/>SQL reads (rule_breakdown, fx_fragility,<br/>review_groups, bucket_loans...)"]
        ReviewActions["agent/review_actions.py<br/>accept/ignore/manual decisions"]
        Rule3["agent/rule3_graph.py<br/>LangGraph substitute-asset agent"]
        Reports["app/reports.py<br/>PDF/CSV generation"]
    end

    subgraph PIPE["Engine 1 pipeline — pipeline/run_evaluation.py"]
        direction TB
        ParsePDF["parse_pdf.py<br/>company-reference.pdf → companies.json (cached)"]
        ComputeInputs["compute_inputs.py<br/>build per-loan OPA input"]
        FX["fx.py<br/>live FX rates (force_refresh) + fallback cache"]
        OpaClient["opa_client.py<br/>POST batch of 500 loans"]
    end

    subgraph OPAC["OPA — Podman container (:8181)"]
        Rego["policies/*.rego<br/>main.rego, rule1_min_value,<br/>rule2_currency, rule3_coverage"]
    end

    subgraph DB["SQLite — data/compliance.db (pipeline/db.py)"]
        T1[("loans")]
        T2[("companies / assets")]
        T3[("rule_results (per run_id)")]
        T4[("suggestions")]
        T5[("audit_events")]
        T6[("run_meta")]
    end

    subgraph EXT["External services"]
        Azure["Azure OpenAI<br/>agent/llm_client.py<br/>MODEL_CHAT / MODEL_ORCHESTRATOR"]
        FXAPI["FX rate API"]
    end

    Dashboard & Review & Insights & Compliance & History -->|fetch /api/*| API
    Assistant --> R5

    R1 --> PIPE
    R2 --> Queries
    R3 --> Queries
    R3 --> ReviewActions
    R4 --> Queries
    R5 --> Queries
    R6 --> Reports

    ReviewActions --> Rule3
    Rule3 --> Azure
    R5 --> Azure

    ParsePDF --> ComputeInputs
    FX --> ComputeInputs
    FX --> FXAPI
    ComputeInputs --> OpaClient
    OpaClient -->|POST /v1/data/compliance/results| Rego
    Rego -->|verdicts by loan_id| OpaClient
    OpaClient --> DB

    Queries --> DB
    ReviewActions --> DB
    Reports --> DB
```

## Key structural notes

- **Frontend** (`frontend/src/App.jsx`): single-page app, 5 tabs, calls `/api/*`
  in parallel via `loadAllData()`, proxied by Vite to `:8000`.
- **Backend** (`backend/app/main.py`): one FastAPI app, thin route layer —
  all real logic lives in `queries.py` (reads) and `review_actions.py`
  (writes/decisions).
- **Engine 1 pipeline** (`backend/pipeline/run_evaluation.py`): streams
  `loans.csv`, batches 500 loans per OPA call, persists incrementally —
  never loads the whole dataset into memory.
- **OPA** (`docker-compose.yml`): runs as a Podman container, policies
  mounted read-only from `backend/policies`, evaluated as pure Rego rules
  (rule1 = min value, rule2 = currency match, rule3 = coverage ratio).
- **DB** (`backend/pipeline/db.py`): SQLite, keyed by `(loan_id, run_id)` so
  history isn't overwritten across runs; `audit_events` is the append-only
  timeline.
- **Agent layer**: only Rule 3 (asset substitution) and the
  assistant/insights narration touch the LLM (`backend/agent/llm_client.py`)
  — Rules 1/2 are fully deterministic.
