# Engine 4 — Asset-Value Predictor (Stretch)

> The brief's **named stretch goal**: a small regression that estimates a suitable
> underwriting asset value for a loan, so the Rule 3 remediation agent has a
> defensible target number when the company's actual holdings contain no qualifying
> asset. Optional per the brief, and to be built **only after the core (Engine 1 +
> Engine 2 + review app + report) is solid**.
>
> This document assumes the [Engine 1](./ENGINE1_README.md) and
> [Engine 2](./ENGINE2_README.md) READMEs, and the broader
> [Insights & Report proposal](./Insights_and_Report.md), where this predictor is
> the *forecast-only* item that stands apart from the anomaly/forecast pairs.

---

## Table of contents

1. [Scope & role in the system](#1-scope)
2. [Why this is not "LLM guesses a number"](#2-not-llm)
3. [Training data — and the contamination fix](#3-data)
4. [Features](#4-features)
5. [The train/test split — the graded artifact](#5-split)
6. [Target: value vs. ratio (open decision)](#6-target)
7. [Model choice (open decision)](#7-model)
8. [Agent integration — where the predictor plugs in](#8-integration)
9. [Validation & what to report](#9-validation)
10. [Priority & when to build](#10-priority)
11. [Locked design decisions & rationale](#11-locked)
12. [Open decisions to confirm before building](#12-open)

---

<a name="1-scope"></a>
## 1. Scope & role in the system

The predictor answers one question: **"For a loan of these characteristics, what
asset value would typically be considered adequate underwriting?"** It returns one
number plus an error range.

It does **not** decide whether Rule 3 passes — OPA still evaluates the *actual*
pledged `asset_value` against `0.5 * loan_value`. The predictor is not a verdict, it
is a reference number. Its operational job is narrow and specific: **enrich the
"honest dead-end" branch of Rule 3 remediation.**

Rule 3's remediation flow, with the predictor slotted in:

```mermaid
flowchart TD
    F[Rule 3 fails] --> R[retrieve_company_assets - deterministic]
    R --> FT[filter_valid_collateral - deterministic]
    FT --> Q{any asset clears 50%?}
    Q -->|yes ~96% of cases| LLM[agent picks + explains<br/>from candidate set]
    Q -->|no ~4% of cases - the dead-ends| PRED[predict_asset_value<br/>returns target + RMSE]
    PRED --> N[agent narrates the shortfall<br/>"holdings X, target ~Y, gap Z"]
    LLM --> REV[Reviewer]
    N --> REV
```

The predictor **turns a bare "no adequate collateral available" into a message a
reviewer can act on** — from "we can't fix this" to "we can't fix this, and the
company is roughly €Z short of what a loan like this typically needs." Stronger
dead-end story, no impact on the deterministic verdict.

---

<a name="2-not-llm"></a>
## 2. Why this is not "LLM guesses a number"

An LLM can produce a plausible target value in one prompt. It should not.

- **The brief requires a validated RMSE.** *"You must report your model's
  out-of-sample RMSE… we are as interested in how you approached validating the
  model as in the number itself."* An LLM's output has no train/test set, no
  reproducible error, no methodology to defend — you literally cannot deliver the
  graded artifact with an LLM.
- **It would break the system's boundary.** Engine 1 and Engine 2 are defended by
  one line: *"deterministic tools decide what's true; the agent decides what to do
  about it."* Letting the model produce a *number* here contradicts that line
  everywhere else in the system.
- **A hand-picked formula (e.g. "60% of loan value") is also not a predictor.** It's
  a heuristic. It has no RMSE in a meaningful sense (nothing was fit) and fails the
  brief's ask for a "regression model." A fixed heuristic is fine as a *baseline* to
  compare a real model against, not as a replacement.

The right tools for each Rule 3 job:

| Case | Tool | Why |
|---|---|---|
| Company has qualifying asset(s) — the ~96% case | **LLM selects + explains** from the deterministic candidate set | Judgement over real options + reviewer-facing narrative |
| Company has none — the ~4% dead-end case | **Predictor** returns a target number with error range; LLM narrates | LLM cannot produce a defensible number; regressor can |
| Any asset in the catalog is wildly off from typical | **Predictor as anomaly check** (`|actual − predicted| / predicted` large) | LLM has no reference distribution for "typical asset value" |

Same predictor read two ways: **fallback estimator** (in remediation) and
**anomaly detector** (over the catalog). One model, two uses — the tidy version of
the "asset-value outliers" idea from the broader Insights doc.

---

<a name="3-data"></a>
## 3. Training data — and the contamination fix

Training data is entirely internal: `loans.csv` joined to the parsed
`company-reference.pdf` (i.e. `companies` + `assets` in the Engine 1 data model).
Each loan row is a labeled example — features from the join, label is `asset_value`.
~100,000 rows before filtering. No external data.

**The important honest note: the dataset is contaminated for this task.** The
`asset_value` column contains what was *actually* pledged, some of which are the
very Rule 3 failures the predictor exists to help fix. Training on all rows learns
the average of good *and* bad underwriting, which is not what we want the predictor
to represent.

**Decision: train only on Rule-3-passing loans** — rows where
`asset_value >= 0.5 * loan_value`. The model then learns the pattern of *adequate*
underwriting, so its predictions represent what an appropriate asset value looks
like for a given kind of loan. That is what the dead-end branch actually needs.

> **Defensible one-liner:** *"We filtered the training set to Rule-3-passing loans
> so the model learns adequate collateral, not the average that includes the
> failures. Otherwise the target itself would be contaminated by the cases we
> exist to warn about."*

This gives roughly 93k training rows (100k minus the ~6,181 Rule 3 failures) —
still plenty.

---

<a name="4-features"></a>
## 4. Features

Six to eight carefully chosen features beat forty auto-extracted ones for a model
you have to defend line by line. Every feature must be usable at inference (nothing
that requires the label).

| Feature | Source | Notes |
|---|---|---|
| `loan_value` | `loans.csv` | The dominant driver — bigger loans structurally need bigger collateral. Consider log-transform |
| `hq_country` (or derived `region`, e.g. eurozone / non-eurozone) | joined | Regional underwriting patterns |
| `industry` | parsed PDF | Different industries pledge different asset scales |
| `loan_currency` | `loans.csv` | Correlated with country, but carries residual signal |
| `asset_category` | `asset_description` bucketed | e.g. warehouse / processing plant / freight hub / distribution centre — **hand-mapped from the ~5 categories seen**, not ML-classified. A judge-defensible mapping beats a fragile classifier |
| Company-level aggregates (optional) | derived | e.g. median asset value the company holds — captures borrower scale without leaking identity across split |

Two rules:

- **No leakage features.** Anything derived from the label (`asset_value`), or
  anything that only exists because the loan is in the training set, is out.
- **Feature list is stable across train and test.** No adding features only in test.

---

<a name="5-split"></a>
## 5. The train/test split — the graded artifact

**This is the piece the assessment cares about most, more than the model choice.**
The brief says outright they will grade validation methodology as much as the RMSE
number.

**Split by company, not by row.** A random 80/20 row split leaks: the same company
appears in both train and test, and the model effectively memorises each company's
typical asset scale. Since the real job of the predictor is generalising to *new*
borrowers (or filling in gaps for known ones), the honest split is:

- **Train on ~80 companies.**
- **Test on ~20 unseen companies.**
- Same ~93k Rule-3-passing rows overall, but no borrower appears in both.

**Defensible one-liner:** *"I split by company because random splitting leaks —
the model would recognise borrowers rather than learn to underwrite. Splitting by
company measures generalisation to new customers, which is the actual use case."*

If time allows, wrap this in **k-fold cross-validation by company** (rotate which
~20 are held out; report mean and spread of RMSE across folds). Same 93k rows, every
company held out exactly once. This turns "here's my RMSE" into "here's my RMSE
across five splits, with the variance you'd expect" — genuine methodology rather
than a single lucky number.

---

<a name="6-target"></a>
## 6. Target: value vs. ratio (open decision)

Two defensible options; pick one and defend it.

- **Predict `asset_value` directly** — simpler and easier to explain. Consider
  log-transforming both target and `loan_value`, since asset values span orders of
  magnitude and RMSE on the log scale is more meaningful across scales.
- **Predict `coverage_ratio` = `asset_value / loan_value`, then multiply back by
  `loan_value` at inference** — often tighter and generalises better across loan
  sizes, because it strips the raw-size effect and lets the model focus on the
  *pattern* of adequate coverage.

**Recommended:** predict the **coverage ratio**, then multiply back. Two reasons: it
tends to give lower RMSE and it directly matches the compliance rule (50% coverage
is the meaningful quantity, not the raw euro amount). The ratio is naturally
bounded and homoscedastic; raw values are not.

Confirm before building — this decision changes the training script and the RMSE
number.

---

<a name="7-model"></a>
## 7. Model choice (open decision)

**The model family matters less than the split.** All of these will produce a
credible RMSE on this data:

| Family | Pros | Cons |
|---|---|---|
| **Linear regression** (with log-transform) | Most explainable — coefficients state directly how each feature moves the estimate; fully deterministic; trivial to defend | May miss nonlinear interactions |
| **Gradient boosting** (LightGBM / XGBoost) | Handles mixed numeric/categorical cleanly; no scaling; free feature-importance; fast on 100k | Less transparent per-prediction; needs seed for reproducibility |
| **Random forest** | Feature-importance built in; robust; simple to explain | Larger models, slower inference |

**Recommended:** **linear regression on log-transformed target and `loan_value`**.
Three reasons:

1. It's the most defensible model in a challenge where the *point* is engineering
   understanding, not benchmark chasing. Coefficients let you point at the equation
   and read it aloud.
2. It's genuinely deterministic — same features in, same prediction out, no seeds
   involved.
3. It sits cleanly next to OPA in the "you can read exactly why it said what it
   said" story you've built the rest of the system on.

Gradient boosting is a fine alternative if linear underfits badly (compare RMSE on
a validation fold before deciding). **Do not build a neural network** — the data
volume doesn't warrant it and it invites "why?" questions with no good answer.

Confirm before building.

---

<a name="8-integration"></a>
## 8. Agent integration — where the predictor plugs in

Predictor is wrapped as the stretch tool listed in the Engine 2 tools table:

```
predict_asset_value(loan) -> {
    predicted_value: <number>,
    rmse: <error range>,
    features_used: {...}
}
```

Two callers, both anticipated in the Engine 2 spec:

**1. Rule 3 dead-end branch (primary use).** After
`filter_valid_collateral(assets, loan_value)` returns an empty candidate set, the
orchestrator calls `predict_asset_value`. The result is passed to the LLM as
context, which then writes a reviewer-facing shortfall message:

> *"Kestrel Pharma holds three assets totalling €1.64M. This loan requires €1.05M
> minimum coverage. Comparable Austrian pharma loans of this size are typically
> underwritten with ~€1.30M in collateral (predictor RMSE ±€180K). The company
> falls short of the strict 50% floor by €890K and of the typical benchmark by
> ~€400K."*

The LLM still narrates; the predictor supplies the anchor number. This is exactly
the "LLM decides what to do, deterministic tool decides what's true" boundary
extended to the dead-end case.

**2. Asset-catalog sanity check (independent use).** Once per run, over the parsed
company assets, flag any asset whose value is far outside what the predictor would
expect for that company's profile (e.g. `|actual − predicted| / predicted > 2`).
Surfaces likely data-entry errors or unusually large holdings *before* the Rule 3
remediation ever tries to substitute them. This is the "asset-value outliers"
anomaly check in the Insights doc, done properly by the same trained model rather
than a hand-picked z-score.

**What the predictor never does:** decide whether Rule 3 passes, override OPA, or
appear in the primary Rule 3 remediation path (where the LLM picks from real
candidates the deterministic filter has already produced).

---

<a name="9-validation"></a>
## 9. Validation & what to report

Report all of the following alongside the model — the brief has said explicitly it
will grade methodology as much as the number:

- **Out-of-sample RMSE** on the held-out companies. If cross-validated by company,
  report **mean RMSE and spread across folds**.
- **Relative error** — RMSE / mean asset value (or MAPE). Raw euros are hard to
  interpret across loan sizes; a percentage gives an intuition-friendly figure.
- **Feature importance / coefficients.** Free with tree models; the equation itself
  for linear. Lets you say "loan value dominates, industry is second, the rest are
  minor" — makes the model feel less like a black box.
- **Predicted vs. actual scatter on the test set.** The single most convincing
  artifact to show a judge — one glance reveals where the model does well and where
  it struggles. Point at it in the demo.
- **Baseline comparison** — RMSE of a trivial heuristic (e.g. "predict = 0.6 ×
  loan_value" or the training-set mean). If the real model doesn't beat these
  meaningfully, that's a finding to report honestly, not hide.

**The one-line story for the presentation:** *"I split by company so the model has
to generalise to unseen borrowers; I trained on Rule-3-passing loans so the target
represents adequate underwriting; I picked linear regression because it's the most
defensible model in a challenge whose grading criterion is explaining every part;
the RMSE on held-out companies is X, versus a trivial baseline of Y."*

That paragraph, delivered clearly, is worth more than a lower RMSE from a leaky
split with no story.

---

<a name="10-priority"></a>
## 10. Priority & when to build

Per the brief's own rule — *"do not start it until the core system (rules, agent,
review app, report) is working end to end"* — this is genuinely last:

1. Engine 1 + Engine 2 + review app + required report solid, end to end.
2. Then this predictor — Day 4 morning at earliest, or an afternoon carved out only
   if the core is truly done.

**If time runs out, skip it and own the skip.** The brief explicitly endorses this:
*"if time is tight, narrow the scope rather than the understanding."* A stronger
presentation is: *"we prioritised the core; here is how we would build the
predictor — filter to Rule-3-passing loans, features from the join, split by
company, linear on log-transformed target, report RMSE across k folds"* — than a
half-built predictor that can't answer methodology questions cleanly.

**What must not happen:** presenting an LLM-produced number as if it were the
predictor. The brief will not accept it, and it undermines the determinism story of
the rest of the system.

---

<a name="11-locked"></a>
## 11. Locked design decisions & rationale

| # | Decision | Rationale |
|---|---|---|
| 1 | Predictor is a reference number, never a Rule 3 verdict | Verdict stays with OPA on the actual asset value; keeps the determinism boundary intact |
| 2 | Fills the ~4% Rule 3 dead-end branch; does not replace the LLM's selection | LLM handles the ~96% "pick from real candidates" case; predictor handles "nothing to pick from" — different jobs |
| 3 | Same model doubles as an asset-catalog anomaly detector | One artifact, two uses; the LLM has no reference distribution to detect anomalies |
| 4 | LLM never produces the target number | No validated RMSE possible; fails the brief's graded artifact |
| 5 | Train only on Rule-3-passing loans | Otherwise the model learns the average of good and bad underwriting — target contamination |
| 6 | Split by company, not by row | Random-row split leaks borrower identity; by-company measures generalisation to new customers |
| 7 | Report RMSE + relative error + feature importance + predicted-vs-actual plot + baseline | Methodology is graded as much as the number; a story beats a bare figure |
| 8 | Build only after core is solid; skip cleanly if time runs out | Brief's own sequencing rule; a defended skip beats a broken build |
| 9 | Data is internal only — no external fetch or historical FX | Same "no new data" discipline as the fragility insight; keeps liability surface small |

---

<a name="12-open"></a>
## 12. Open decisions to confirm before building

| # | Decision | Recommendation | Trade-off |
|---|---|---|---|
| A | Target: raw `asset_value` or `coverage_ratio` | **Ratio** (multiply back at inference) | Ratio is tighter and matches the rule; raw is simpler to explain |
| B | Model family: linear vs. gradient boosting vs. RF | **Linear regression** on log-transformed target | Linear is the most defensible; gradient boosting is a fine fallback if linear underfits materially |
| C | Cross-validation depth: single split vs. k-fold by company | **5-fold by company if time allows**, else single split | k-fold gives spread; single split is faster |
| D | Include company-level aggregates as features | **Yes, cautiously** (median asset value etc.) — but derive them from *training* data only, per fold | Adds signal; watch for cross-fold leakage |
| E | Feature-drop test in the report | **Yes, one drop** (retrain without `loan_value`) to show it dominates | Free credibility on feature importance |

---

### Relationship to the rest of the system

- **Engine 1** produces `loans` + `companies` + `assets` — the predictor's training
  join. Also produces the run's `rule_results`, from which the "Rule-3-passing"
  training filter is derived.
- **Engine 2** owns the orchestration that calls `predict_asset_value` on the
  dead-end branch and lets the LLM narrate the result.
- **Engine 3 (FX-boundary fragility)** and this predictor are independent — they
  operate on different data (`loan_value_eur` vs. `asset_value`) and serve
  different concerns. Both share the same discipline: deterministic arithmetic /
  validated inference, no probabilistic claims about compliance outcomes.
- **The report (see Insights_and_Report.md, section 8)** can optionally include a
  short predictor section — model description, RMSE with methodology, baseline
  comparison — as evidence the stretch was attempted honestly.
