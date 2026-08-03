# Loan Compliance Challenge: Project Brief

**Format:** 4-day build assessment · Teams of 3-4 · Judged by live presentation and demo

---

## 1. What this is

A bank has given out a large number of loans, each secured against a pledged
asset. Before these loans can be reported, they need to pass a small set of
compliance checks. Your task is to build an agentic system that checks every
loan against three rules, and for anything that fails, gives a human reviewer
three options: fix it manually, ignore it, or accept a fix an AI agent
suggests.

You are given everything you need: the loan data, a reference document on the
100 companies involved, and this brief. Nothing else is provided, and nothing
else should be needed.

There is no hidden test set and no automated score. You will present your
system and defend your design choices to the judges. What matters is a system
that actually runs against the full dataset, rules enforced through OPA and
Rego rather than left to a model's judgement, and an ability to explain why
you built it the way you did.

## 2. What we are actually assessing

Read this section carefully. It matters more than any other part of the
brief.

**We are assessing engineering understanding, not the polish of what gets
demoed.** A slick-looking app that nobody on the team can explain is a fail,
regardless of how well it runs. We would much rather see a rough interface
backed by an architecture every team member understands deeply than a
smooth one nobody can account for.

Concretely, this means:

- **You must be able to explain every part of your system.** If a judge points
  at a piece of code, a Rego rule, an agent prompt, or a design decision,
  whoever is asked should be able to say what it does and why it's built that
  way, without deferring to "the AI wrote that part." Using AI coding
  assistants is expected and encouraged (see below), but the understanding has
  to be yours.
- **Vibe-coded output is not acceptable.** Generating a large surface area of
  code you have not read, reasoned about, or tested is the opposite of what
  this assessment is for. If you can't trace a bug in it yourself, you have
  built too much too fast.
- **We are watching how you work, not just what you ship.** Code structure,
  commit history, how you split responsibilities across the team, whether you
  tested your rules, whether your architecture actually separates concerns —
  all of this is visible to judges and all of it counts. Two teams that end up
  with similar-looking demos can and will be assessed very differently based
  on this.
- **If you have to choose between scope and understanding, choose
  understanding.** A team that implements one rule properly, in code they can
  fully explain, has done better work than a team that implements three rules
  through code they generated and never really read.

AI coding assistants (Copilot, Claude, Cursor, and similar) are allowed and
expected — this reflects how the work is actually done. The bar is not
"did you use AI," it's "do you understand what it built." Be ready to have
that conversation in detail during your presentation.

## 3. What you're given

Three files, all in this pack.

1. **`loans.csv`** — around 100,000 rows, one per loan. Columns: `loan_id`,
   `company_name`, `hq_country`, `asset_description`, `asset_value`,
   `asset_owner`, `loan_value`, `loan_currency`.
2. **`company-reference.pdf`** — a profile for each of the 100 companies the
   loans belong to: headquarters country, industry, the assets that company
   can pledge with their value, and the related entities that may appear as
   an asset's recorded owner. This is what your retrieval agent searches.
3. **This brief.**

A few things about the data worth knowing before you start:

- `asset_owner` is sometimes the company itself, sometimes a subsidiary,
  sometimes a related holding entity. No rule checks this column. It is
  realistic noise, not a signal to chase.
- `asset_value` and `loan_value` are both expressed in `loan_currency`. You
  never need to convert between them to check rule 3.
- The reference PDF states each company's headquarters **country**, not its
  currency. Building the country-to-currency mapping is your job, and it is
  part of what rule 2 is testing.

## 4. The rules

Implement all three. Each is deterministic: given the inputs, there is exactly
one correct answer, and that answer must come from a **rule engine (OPA,
policy written in Rego)**, not from a model asked to judge the record.

### Rule 1 — Minimum loan value

**A loan must be worth more than EUR 25,000. If it is reported in a currency
other than EUR, convert it to EUR at the exchange rate on the day of the
check, and compare the converted value.**

You will need a live foreign exchange rate. A couple of free options with no
API key required, to get you started:

- **Frankfurter** — `https://api.frankfurter.dev` (built on ECB reference rates)
- **exchangerate.host** — `https://exchangerate.host`

You are free to use either, another free source, or your own approach.
Whichever you pick, expect the exact EUR value of borderline loans to shift
slightly day to day as rates move. That's expected, not a bug in the data:
this rule is partly testing how you handle a live external dependency, not
just the arithmetic. Think about caching the rate for the run rather than
calling the API once per row, and about what your pipeline does if the API is
slow or unavailable.

One implementation note: Rego policies should not make network calls. Fetch
and convert the rate in your pipeline, and pass OPA the already-converted EUR
figure. OPA's job is to compare that figure to the threshold, not to fetch
exchange rates itself.

**Remediation guidance:** a loan that fails this rule is out of scope for
reporting. The suggested fix is not a corrected number — there is nothing to
correct. The agent should tell the reviewer this loan should be **removed
from the report**.

### Rule 2 — Currency must match the country of headquarters

**A loan must be reported in the currency of the country where the borrowing
company is headquartered.**

The company's headquarters country is in `company-reference.pdf`. There is no
column in the CSV that states the correct currency directly — you have to
derive it. Build a static country-to-currency lookup table once (for example:
Germany, Ireland, Spain, France, and several other countries in the data use
EUR; the United Kingdom uses GBP; the United States uses USD; and a handful of
others each use their own currency). Querying an LLM for this on every row
would be slow, non-deterministic, and pointless, since the mapping never
changes at runtime — a static table you build once is the right answer here,
and part of what this rule is testing is whether you reach for that or not.

**Remediation guidance:** when the currency doesn't match, the agent should
look up the company's headquarters country in the reference PDF, resolve it
to the correct currency via your table, and suggest that currency as the fix.
For example, if a company headquartered in Germany has a loan reported in USD,
the suggested fix is: change the currency to EUR.

### Rule 3 — Asset coverage

**The value of the pledged asset must be at least 50% of the loan value.**
(`asset_value >= 0.5 * loan_value`, both already in the same currency — no
conversion needed.)

**Remediation guidance:** this is where retrieval matters. When a loan fails
this rule, the agent should look up the borrowing company in
`company-reference.pdf`, find another asset in that company's asset list
that would satisfy the 50% threshold for this loan, and suggest substituting
it. If no asset the company holds would satisfy the threshold, say so rather
than forcing a suggestion — the reviewer needs to know the loan genuinely has
no adequate collateral available, not receive a fix that doesn't actually
work.

This rule is the one place in the challenge built specifically to exercise
RAG. Retrieval quality and how you evaluate it are both part of what you'll
be asked about.

## 5. What you build

**A rule engine.** Each rule implemented as a Rego policy, evaluated by an OPA
server. Your pipeline computes whatever inputs a rule needs (the EUR-converted
loan value, the correct currency for a company, etc.) and OPA returns the
pass/fail decision. The decision itself should not depend on a model's
judgement call.

**An AI suggestion agent.** For each failing rule, generates the fix described
in section 4 above, using the reference PDF where relevant. This is where your
retrieval and reasoning happens — the verdict comes from OPA, the explanation
and the suggested fix come from your agent.

**A review application**, with a human in the loop. For every loan that fails
at least one rule, a reviewer should be able to see what failed and why, and
choose one of three actions:

1. **Fix manually** — edit the row themselves.
2. **Ignore** — leave it as is and move on.
3. **Accept the AI-suggested fix** — apply what the agent proposed.

The dataset is around 100,000 rows. Loading everything into memory and
rendering it all at once will not hold up — build with that scale in mind
from the start, not as an afterthought. You do not need to make every single
row beautiful; you do need the tool to stay usable at this size.

**A report**, generated from a review pass over the data, showing:

- Total loans checked.
- How many failed at least one rule, broken down by rule (how many failed
  rule 1, rule 2, rule 3 — not just a single combined failure count).
- How many were fixed (manually or via the AI suggestion), and how many were
  left as ignored / unresolved.
- Total value of loans given out per company, so this doubles as a simple
  portfolio summary alongside the compliance results.

A reminder from section 2: if time is tight, narrow the scope rather than the
understanding. One rule you can fully explain and defend beats three rules
generated wholesale and never really read.

## 6. Stretch goal (optional): asset value predictor

If your core system is solid and working, and only then, there is an optional
extension.

Build a simple regression model that predicts what a suitable underwriting
asset value should be, given features like the company's region, the loan
value, the asset type, and whatever else you think is relevant. Wrap it as an
agent that can be called with a company/loan's details and returns a
predicted asset value — for instance, as an additional input to the rule 3
suggestion agent, or as a standalone check.

You must report your model's **out-of-sample RMSE**. How you construct that
evaluation — your train/test split, cross-validation, what you hold out and
why — is entirely up to you. We are as interested in how you approached
validating the model as in the number itself, so be ready to explain your
methodology.

This is a genuine stretch and a different skill from the rest of the
challenge. Do not start it until the core system (rules, agent, review app,
report) is working end to end.

## 7. Schedule

Before day 1, it's worth setting up OPA and confirming you can reach a free FX
API, so day 1 afternoon starts with building rather than environment setup.

| When | Activity |
|---|---|
| **Day 1, AM** | Introduction and welcome. Walk through this brief, the rules, and the three files together. |
| **Day 1, PM** | Break into teams. Design your architecture and start building the core: one rule working end to end through OPA. |
| **Day 2** | Full day build. Get all three rules working, the suggestion agent producing real fixes, and the review app running. |
| **Day 3** | Full day build. Get the review app handling the full-scale dataset, generate the report, and harden anything that's still fragile. Only once the core is solid, attempt the stretch goal. |
| **Day 4, AM** | Teams present and demo live. |
| **Day 4, PM** | Wrap-up. |

## 8. What to bring to the presentation

Since there's no automated score, this is what you're judged on. Come ready
to:

- **Walk through your architecture** — what agents you built, how they talk
  to each other and to OPA, and where retrieval fits in.
- **Demo live** against a sample of the real data, not a canned example.
- **Defend the deterministic-vs-probabilistic split** — explain exactly what
  OPA decides versus what your model decides, and why you drew the line
  there.
- **Show the report** and talk through what it tells a reviewer at a glance.
- **If you attempted the stretch goal**, explain your validation methodology
  for the RMSE figure, not just state the number.

Expect judges to pick a piece of your system at random — a Rego rule, a
section of the pipeline, an agent's prompt — and ask whoever is presenting to
explain it. Any team member should be able to answer for any part of the
system. This is deliberate: it is the main way we tell genuine engineering
work apart from output nobody on the team actually understands.

## 9. What good looks like

- Every person on the team can explain every part of the system, including
  the parts an AI assistant helped write. This is the single most important
  item on this list.
- The rule engine, not the model, makes the pass/fail call. Every verdict
  traces back to a specific Rego policy a judge could read.
- Suggested fixes are genuinely useful: rule 1 tells the reviewer to remove
  the loan, rule 2 proposes the correct currency backed by your country table,
  and rule 3 proposes a real alternative asset from the company's actual
  holdings, or honestly says none exists.
- The review app stays usable at 100,000 rows.
- The report gives a clear, per-rule picture of what was found and what
  happened to it.
- You can explain every design choice, especially the boundary between what
  the model does and what the rule engine does.
