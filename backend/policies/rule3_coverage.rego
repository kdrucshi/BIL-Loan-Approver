# Rule 3 - Asset coverage.
#
# The pledged asset's value must be at least 50% of the loan value. Both
# figures are already in loan_currency (no FX conversion for this rule -
# coverage is currency-invariant). `>=`: exactly 50% PASSES
# (Evaluation_Engine.md §3 - opposite boundary direction to Rule 1).
package compliance

import rego.v1

rule3_coverage_ratio(loan) := loan.asset_value / loan.loan_value

rule3_pass(loan) := rule3_coverage_ratio(loan) >= 0.5

rule3_result(loan) := {
	"pass": rule3_pass(loan),
	"coverage_ratio": rule3_coverage_ratio(loan),
	"required": 0.5,
}
