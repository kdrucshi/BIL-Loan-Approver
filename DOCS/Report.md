# Engine 3 — Compliance Report

> The output of a review pass over the data. Generated **from aggregates already
> computed by Engine 1 and Engine 2** (`run_meta`, `rule_results`, `loans`,
> `audit_events`) — this engine does not recompute anything, it only reads and
> formats. Two export formats, two different audiences: a **PDF** summary for a
> human to read top to bottom, and a **CSV** row-level export for further
> analysis in Excel/BI tools.

This document assumes the data model in [Evaluation_Engine.md](./Evaluation_Engine.md#10-data-model)
(`loans`, `companies`, `assets`, `rule_results`, `audit_events`, `run_meta`) and the
review flow in [Action_Engine.md](./Action_Engine.md).

---

## 1. Why two formats, not one

| | PDF | CSV |
|---|---|---|
| Audience | Judge / reviewer / compliance officer | Analyst / downstream system |
| Shape | Narrative + aggregate tables | One row per loan, flat |
| Built from | `run_meta` + grouped counts only | `loans` ⋈ `rule_results` ⋈ resolution |
| Never contains | All 100,000 rows | Prose/explanation |

Same source of truth, different job. The PDF must never try to render all
100,000 rows (defeats the "stays usable at scale" requirement); the CSV must
never summarize — a downstream tool needs every row.

---

## 2. PDF — human-readable summary report

Satisfies the brief's report requirements (section 5) as a narrative. Built
**only from aggregates** — `run_meta` plus grouped counts — never from a per-row
render.

### 2.1 Run header

| Field | Source |
|---|---|
| `run_id` | `run_meta.run_id` |
| Run timestamp (started / completed) | `run_meta.started_at` / `completed_at` |
| Total loans checked | `run_meta.total_loans` |
| FX rate date | `run_meta.fx_rate_date` |
| FX source used (primary / secondary) | `run_meta.fx_source` |
| Stale FX flag | `run_meta.fx_stale` |

### 2.2 Headline compliance score

| Field | Source |
|---|---|
| Pre-review compliance % | `run_meta.pre_review_compliance` |
| Post-review compliance % | `run_meta.post_review_compliance` |
| Δ (points healed) | `post_review_compliance - pre_review_compliance` |

### 2.3 Per-rule breakdown (required — not a single combined count)

| Rule | Passed | Failed | Fail % |
|---|---|---|---|
| Rule 1 — min loan value | `total_loans - rule1_fails` | `run_meta.rule1_fails` | `rule1_fails / total_loans` |
| Rule 2 — currency matches HQ | `total_loans - rule2_fails` | `run_meta.rule2_fails` | `rule2_fails / total_loans` |
| Rule 3 — asset coverage | `total_loans - rule3_fails` | `run_meta.rule3_fails` | `rule3_fails / total_loans` |

### 2.4 Disposition summary

Of the loans that failed at least one rule:

| Field | Source |
|---|---|
| Fixed manually | `run_meta.fixed` (manual subset, from `audit_events` where `source='reviewer'` action = manual edit) |
| Fixed via accepted AI suggestion | `audit_events` count where action = `accepted_ai_fix` |
| Ignored | `run_meta.ignored` |
| Unresolved | `run_meta.unresolved` |
| Removed (Rule 1, post-recheck) | `run_meta.removed` |

**The rescue note (explicitly worth surfacing, not just knowing for the demo):**
> "`X` failed Rule 1 at evaluation; `Y` were rescued by a currency fix and
> re-check; `Z` were genuinely removed."
Where `X` = raw Rule 1 evaluation-failure count, `Z` = `run_meta.removed`,
`Y = X - Z`. See [Evaluation_Engine.md § 8](./Evaluation_Engine.md#8-rule-interactions).

### 2.5 Portfolio summary

Total value of loans given out per company (doubles as the brief's simple
portfolio summary), from `loans` grouped by `company_name`:

| Company | HQ country | # loans | Total loan value |
|---|---|---|---|
| … | … | … | … |

Full table in the CSV; PDF shows top N by exposure + a grand total.

### 2.6 Review-group summary

One row per review group (deterministic fix-signature groups from
[Action_Engine.md § 8](./Action_Engine.md#8-grouping)):

| Group | Rule | Fix | Loan count | Resolved | Open |
|---|---|---|---|---|---|

### 2.7 Methodology footnote

- Country → currency table version (static, hand-built — see
  [Evaluation_Engine.md § 6](./Evaluation_Engine.md#6-currency-resolution)).
- FX fallback behaviour used this run (primary / secondary / stale-cache).
- OPA policy bundle / Rego package version.

This makes the PDF self-contained evidence of **how** the verdict was reached,
not just **what** it was.

---

## 3. CSV — row-level data export

One row per loan. Flat, complete, no prose. Built by streaming the join
row-by-row from SQLite (never loading all 100k into memory).

### 3.1 Columns

| Column | Meaning | Source |
|---|---|---|
| `loan_id` | Primary key | `loans.loan_id` |
| `company_name` | Borrower | `loans.company_name` |
| `hq_country` | As stated in CSV (validated against PDF) | `loans.hq_country` |
| `loan_value` | Original amount | `loans.loan_value` |
| `loan_currency` | Original currency | `loans.loan_currency` |
| `loan_value_eur` | EUR-converted (Rule 1 input) | `rule_results.loan_value_eur` |
| `asset_description` | Pledged asset | `loans.asset_description` |
| `asset_value` | Pledged asset value | `loans.asset_value` |
| `coverage_ratio` | `asset_value / loan_value` | `rule_results.coverage_ratio` |
| `rule1_pass` | bool | `rule_results.rule1_pass` |
| `rule2_pass` | bool | `rule_results.rule2_pass` |
| `rule3_pass` | bool | `rule_results.rule3_pass` |
| `expected_currency` | Rule 2's correct answer | `rule_results.expected_currency` |
| `overall_status` | `compliant` / `has_failures` / `removed` / `resolved` | `loans.overall_status` |
| `resolution` | `manual` / `accepted_ai_fix` / `ignored` / `removed` / `compliant` | derived from `audit_events` |
| `applied_fix_rule` | which rule the applied fix addressed (nullable) | `audit_events.meta.rule` |
| `applied_fix_from` / `applied_fix_to` | the changed value, if any | `audit_events.meta.from` / `meta.to` |
| `run_id` | which run produced this row | `rule_results.run_id` |
| `fx_rate_date` | for reproducibility of `loan_value_eur` | `run_meta.fx_rate_date` |

### 3.2 What it never contains

- No agent explanations or suggestion text (those are ephemeral per
  [Action_Engine.md § 11](./Action_Engine.md#11-audit) — only *accepted, applied*
  values are facts worth exporting).
- No aggregate-only figures (compliance %, per-rule totals) — those belong in
  the PDF; the CSV is one row per loan so a consumer can recompute any aggregate
  itself.

---

## 4. Generation notes

- **PDF**: build from `run_meta` + `GROUP BY` queries only — never iterate all
  loans to build it.
- **CSV**: stream the `loans ⋈ rule_results ⋈ audit_events` join and write
  row-by-row; do not materialize the full result set in memory first.
- Both are generated **per run** (`run_id`), so a past run in the History view
  can still be re-exported, not just the latest.
- Brief checklist this satisfies (section 5 / section 9): total checked,
  per-rule failure breakdown, fixed/ignored/unresolved counts, portfolio value
  per company — all present in the PDF; all reconstructable from the CSV.
