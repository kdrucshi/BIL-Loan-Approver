# Compliance Report — PDF Generation Spec

> Hand this file to your code editor / AI assistant when building the PDF report.
> It describes exactly what the PDF should contain, what data to query, and how
> to lay it out. Replaces the current flat text dump with a structured,
> visually clear report a compliance officer can scan in 30 seconds.

---

## 0. Tech stack

Use **ReportLab** (`reportlab`) with Platypus for layout. It's already available
and gives full control over spacing, colors, and tables.

```bash
pip install reportlab --break-system-packages
```

Page size: **A4 portrait**. Margins: 50pt left/right, 40pt top/bottom.

---

## 1. Page 1 — Header + headline score + per-rule breakdown + overlap

### 1.1 Report header (top of page)

Left-aligned:
- **Title**: "Loan compliance report" — 24pt, bold
- **Subtitle**: "Kyndryl — Secured loan portfolio review" — 12pt, gray

Right-aligned:
- **Date**: human-readable run date, e.g. "4 August 2026" — 12pt
- **Run ID**: `run_meta.run_id` — 10pt, monospace, gray

**Source:**
```sql
SELECT run_id, started_at, completed_at, fx_rate_date, fx_source, fx_stale
FROM run_meta WHERE run_id = :current_run_id
```

### 1.2 Headline compliance score

A visually prominent section — the first thing anyone reads.

Layout: two columns side by side.

**Left column:**
- Label: "Compliance score (pre-review)" — 11pt, gray
- Big number: `pre_review_compliance` — **48pt bold**, e.g. "78.55%"
- Subtext: "{unique_failing_loans} of {total_loans} loans have failures" — 12pt, gray

**Right column:**
- Label: "Post-review" — 11pt, gray
- Number: `post_review_compliance` — 28pt bold
- Delta badge: "+X.XX pts" or if delta is 0: "+0.00 pts (no review actions taken yet)"
  - Color the badge: green if delta > 0, gray if delta == 0, red if delta < 0

**Source:**
```sql
SELECT
  total_loans,
  pre_review_compliance,
  post_review_compliance,
  (post_review_compliance - pre_review_compliance) AS delta
FROM run_meta WHERE run_id = :current_run_id
```

For `unique_failing_loans`:
```sql
SELECT COUNT(*) FROM rule_results
WHERE run_id = :current_run_id
  AND (rule1_pass = 0 OR rule2_pass = 0 OR rule3_pass = 0)
```

---

### 1.3 Per-rule breakdown table

**THIS IS THE KEY CHANGE: add EUR exposure column.**

| Column        | Content                              |
|---------------|--------------------------------------|
| Rule tag      | Colored pill: R1 = red, R2 = amber, R3 = blue |
| Rule name     | "Minimum loan value (EUR 25k)" etc.  |
| Failed        | Count, bold                          |
| EUR exposure  | SUM of `loan_value_eur` for failing loans of that rule |
| Fail %        | `failed / total_loans * 100`         |
| Mini bar      | Proportional bar showing fail % visually |

**Source:**
```sql
-- Rule 1 failures + EUR exposure
SELECT
  COUNT(*) AS failed,
  SUM(loan_value_eur) AS eur_exposure
FROM rule_results
WHERE run_id = :current_run_id AND rule1_pass = 0

-- Repeat for rule2_pass, rule3_pass
```

**Formatting:**
- EUR exposure: format as "€118.7M" or "€1.42B" (use abbreviations, not raw numbers)
- Fail %: one decimal, e.g. "11.31%"
- Mini bar: a small colored rectangle proportional to fail %, max width ~80pt

---

### 1.4 Overlap callout

A colored info box (light blue background, blue text) immediately after the rule table:

> "Rule totals (24,674) exceed unique failing loans (21,452) because 3,038
> loans fail multiple rules. See overlap table below."

The numbers are computed:
- Rule totals = rule1_fails + rule2_fails + rule3_fails
- Unique failing = COUNT of loans failing at least one rule
- Overlap count = rule_totals - unique_failing

---

### 1.5 Rule overlap section

**Three metric boxes** in a row (like dashboard cards):
- "18,414 — Single rule only"
- "2,854 — Exactly 2 rules"
- "184 — All 3 rules"

Then an **overlap table** with 7 rows:

| Combination  | Count |
|-------------|-------|
| R1 only     | 9,208 |
| R3 only     | 4,806 |
| R2 only     | 4,400 |
| R1 + R2     | 1,663 |
| R2 + R3     | 932   |
| R1 + R3     | 259   |
| R1 + R2 + R3| 184   |

**Source:**
```sql
SELECT
  rule1_pass, rule2_pass, rule3_pass,
  COUNT(*) AS cnt
FROM rule_results
WHERE run_id = :current_run_id
  AND (rule1_pass = 0 OR rule2_pass = 0 OR rule3_pass = 0)
GROUP BY rule1_pass, rule2_pass, rule3_pass
ORDER BY cnt DESC
```

Map the boolean combos to labels in Python. Sort by count descending.

---

## 2. Page 2 — Disposition + portfolio + methodology

### 2.1 Disposition summary

**Important: if all counts are 0, show a warning callout** (red background):
> "No review actions have been taken yet. All {unique_failing} failures are unresolved."

Table columns:

| Disposition              | Count | EUR value       |
|--------------------------|-------|-----------------|
| Fixed manually           | N     | €X              |
| Fixed via AI suggestion  | N     | €X              |
| Ignored                  | N     | €X              |
| Removed (Rule 1)         | N     | €X              |
| **Unresolved**           | **N** | **€X** (bold)   |

**The unresolved row should be visually emphasized** — bold, or a light gray background.

**Source:**
```sql
SELECT
  resolution,
  COUNT(*) AS cnt,
  SUM(loan_value_eur) AS eur_value
FROM (
  SELECT
    rr.loan_value_eur,
    COALESCE(ae.resolution, 'unresolved') AS resolution
  FROM rule_results rr
  LEFT JOIN audit_events ae ON rr.loan_id = ae.loan_id AND ae.run_id = rr.run_id
  WHERE rr.run_id = :current_run_id
    AND (rr.rule1_pass = 0 OR rr.rule2_pass = 0 OR rr.rule3_pass = 0)
)
GROUP BY resolution
```

**Rescue note — ONLY show if review actions have actually happened:**

If `removed > 0`:
> "{X} failed Rule 1 at evaluation; {Y} were rescued by a currency fix and
> re-check; {Z} were genuinely removed."
>
> Where X = raw Rule 1 fail count, Z = removed count, Y = X - Z

If no review actions yet: **do NOT show this note.** It's misleading pre-review.

---

### 2.2 Portfolio summary — top 10 by EUR exposure

**CRITICAL: normalize all values to EUR.** Don't show raw currency values.
You already have `loan_value_eur` — use it.

Table columns:

| Company              | HQ          | Loans | Total (EUR) | Failures |
|----------------------|-------------|-------|-------------|----------|
| Silverlake Textiles  | UK          | 978   | €2.76B      | 123      |
| ...                  | ...         | ...   | ...         | ...      |

- Show top 10 sorted by total EUR exposure descending
- Add a **grand total row** at the bottom
- Failures column: color red if > 0
- Add footnote: "Showing top 10. Full table in CSV export. All values converted to EUR at run-date FX rate."

**Source:**
```sql
SELECT
  l.company_name,
  l.hq_country,
  COUNT(*) AS num_loans,
  SUM(rr.loan_value_eur) AS total_eur,
  SUM(CASE WHEN rr.rule1_pass = 0 OR rr.rule2_pass = 0 OR rr.rule3_pass = 0
      THEN 1 ELSE 0 END) AS failure_count
FROM loans l
JOIN rule_results rr ON l.loan_id = rr.loan_id AND rr.run_id = :current_run_id
GROUP BY l.company_name, l.hq_country
ORDER BY total_eur DESC
LIMIT 10
```

---

### 2.3 Methodology footnote

At the bottom of page 2, smaller text (10pt), gray. Separated by a thin line.

Include:
- Rule engine: "OPA / Rego, package 'compliance'"
- Country-to-currency table: "Static, hand-built ({N} countries, {M} currencies)"
- FX source: "Frankfurter API (ECB rates), dated {fx_rate_date}"
- FX fallback: "exchangerate.host (secondary), last cached rate flagged stale if both unavailable"
- FX status this run: "Primary source" or "Secondary source" or "Stale cache (flagged)"
- Run duration: "{started_at} to {completed_at} ({N} seconds)"

---

## 3. Visual design rules

### Colors (use throughout)

```python
COLORS = {
    'primary':    '#1a1a1a',  # Main text
    'secondary':  '#6b6b6b',  # Labels, supporting text
    'muted':      '#999999',  # Footnotes, placeholders
    'rule1':      '#D93025',  # Red — Rule 1
    'rule1_bg':   '#FDE8E8',  # Light red background
    'rule2':      '#E37400',  # Amber — Rule 2
    'rule2_bg':   '#FFF3E0',  # Light amber background
    'rule3':      '#1A73E8',  # Blue — Rule 3
    'rule3_bg':   '#E8F0FE',  # Light blue background
    'success':    '#0D652D',  # Green — fixed/resolved
    'success_bg': '#E6F4EA',  # Light green background
    'danger_bg':  '#FDE8E8',  # Danger callout background
    'info_bg':    '#E8F0FE',  # Info callout background
    'border':     '#E0E0E0',  # Table borders
    'bar_bg':     '#F0F0F0',  # Mini bar background
}
```

### Typography

- Title: 24pt, bold
- Section heading: 16pt, bold
- Table header: 11pt, gray, uppercase is optional
- Table body: 11pt, regular
- Monospace (IDs, run_id): Courier 10pt
- Footnotes: 10pt, gray

### Table style

```python
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

style = TableStyle([
    ('FONTSIZE', (0, 0), (-1, -1), 11),
    ('FONTSIZE', (0, 0), (-1, 0), 10),          # Header row smaller
    ('TEXTCOLOR', (0, 0), (-1, 0), COLORS['secondary']),  # Header gray
    ('LINEBELOW', (0, 0), (-1, 0), 0.5, COLORS['border']),  # Header underline
    ('LINEBELOW', (0, 1), (-1, -1), 0.25, COLORS['border']),  # Row separators
    ('TOPPADDING', (0, 0), (-1, -1), 6),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ('ALIGN', (-3, 1), (-1, -1), 'RIGHT'),       # Right-align numeric columns
])
```

### Callout boxes

Colored rounded rectangle with padding. No border, just fill color + matching text color.

```python
# Example: info callout
def make_callout(text, bg_color, text_color):
    """Returns a Table styled as a callout box."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import ParagraphStyle

    style = ParagraphStyle('callout', fontSize=11, leading=16, textColor=text_color)
    content = [[Paragraph(text, style)]]
    t = Table(content, colWidths=[None])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('ROUNDEDCORNERS', [6, 6, 6, 6]),
    ]))
    return t
```

### EUR formatting helper

```python
def format_eur(value):
    """Format EUR value with abbreviation: €1.42B, €118.7M, €25.0K"""
    if abs(value) >= 1_000_000_000:
        return f"€{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        return f"€{value / 1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        return f"€{value / 1_000:.1f}K"
    else:
        return f"€{value:,.0f}"
```

---

## 4. Section order (top to bottom)

```
PAGE 1:
┌─────────────────────────────────────┐
│ Report header (title + date + ID)   │
│─────────────────────────────────────│
│ Headline compliance score           │
│   78.55%  (big)    Post: 78.55%     │
│   21,452 of 100,000 have failures  │
│─────────────────────────────────────│
│ Per-rule breakdown table            │
│   R1 | Min loan value | 11,314 | €118.7M | 11.31% | ██░░ │
│   R2 | Currency match | 7,179  | €892.4M | 7.18%  | █░░░ │
│   R3 | Asset coverage | 6,181  | €1.42B  | 6.18%  | █░░░ │
│─────────────────────────────────────│
│ ℹ️ Overlap callout                   │
│   "Rule totals exceed unique..."    │
│─────────────────────────────────────│
│ Rule overlap                        │
│   [18,414 single] [2,854 two] [184] │
│   Combo table (7 rows)              │
└─────────────────────────────────────┘

PAGE 2:
┌─────────────────────────────────────┐
│ ⚠️ Warning callout (if no actions)   │
│   "No review actions taken yet..."  │
│─────────────────────────────────────│
│ Disposition summary table           │
│   Fixed manually      | 0 | —      │
│   Fixed via AI        | 0 | —      │
│   Ignored             | 0 | —      │
│   Removed (R1)        | 0 | —      │
│   Unresolved          | 21,452 | €2.4B │
│─────────────────────────────────────│
│ Rescue note (only if review done)   │
│─────────────────────────────────────│
│ Portfolio summary — top 10 by EUR   │
│   Company | HQ | Loans | EUR | Fails│
│   (all values in EUR, not mixed)    │
│   Grand total row at bottom         │
│─────────────────────────────────────│
│ Methodology footnote                │
│   Rule engine, FX source, table ver │
└─────────────────────────────────────┘
```

---

## 5. What changed from the old report (summary for your team)

| Old (current)                        | New (this spec)                            |
|--------------------------------------|--------------------------------------------|
| No EUR exposure anywhere             | EUR exposure on every table                |
| Rule counts only                     | Counts + EUR value + mini bar              |
| No overlap data                      | 7-row overlap table + metric cards         |
| Rescue note always shown (buggy)     | Only shown after review actions happen     |
| Portfolio in mixed currencies         | All normalized to EUR                      |
| Portfolio has no failure counts       | Failure count per company, colored red     |
| No callouts or warnings              | Info/warning callouts for key insights     |
| Flat text, no visual hierarchy       | Big score number, section headings, color  |
| Methodology crammed in one line      | Structured footnote with all run params    |

---

## 6. CSV — no changes needed

The CSV is already correct per the existing spec. One row per loan, flat,
no prose. The only addition worth considering: add `failure_combination`
column (e.g. "R1", "R1+R2", "R2+R3") so downstream analysts don't have to
derive it from three boolean columns. Optional — not required.

---

## 7. Quick checklist before shipping

- [ ] Compliance score is the biggest text on page 1
- [ ] Every table with counts also has EUR exposure
- [ ] Portfolio values are ALL in EUR (no mixed currencies)
- [ ] Overlap callout explains why rule totals > unique failures
- [ ] Rescue note is NOT shown if disposition counts are all zero
- [ ] Warning callout IS shown if no review actions taken
- [ ] Methodology includes FX source, date, stale flag, run duration
- [ ] Top 10 portfolio has a grand total row
- [ ] Failure count column in portfolio table, colored red if > 0
- [ ] Mini bars in per-rule table are proportional to fail %
- [ ] All numbers are formatted (commas, 1-2 decimals, €X.XM/B)
