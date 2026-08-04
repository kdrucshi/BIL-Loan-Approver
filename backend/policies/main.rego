# Aggregator - exposes all three rules at a single path so a batch of 500
# loans is evaluated in ONE query (Evaluation_Engine.md §7), not three.
# Verdicts are keyed by loan_id, never by array order (the one bug-prone
# spot the doc calls out) - the pipeline must map results back by this key.
package compliance

import rego.v1

results[loan_id] := result if {
	some loan in input.loans
	loan_id := loan.loan_id
	result := {
		"rule1": rule1_result(loan),
		"rule2": rule2_result(loan),
		"rule3": rule3_result(loan),
	}
}
