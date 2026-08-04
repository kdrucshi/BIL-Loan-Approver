package compliance_test

import data.compliance
import rego.v1

# --- Rule 1: strict `>`, exactly-on FAILS ---

test_rule1_just_above if {
	loan := {"loan_id": "L1", "loan_value_eur": 25000.01}
	compliance.rule1_result(loan).pass
}

test_rule1_exactly_on_fails if {
	loan := {"loan_id": "L1", "loan_value_eur": 25000.00}
	not compliance.rule1_result(loan).pass
}

test_rule1_just_below if {
	loan := {"loan_id": "L1", "loan_value_eur": 24999.99}
	not compliance.rule1_result(loan).pass
}

# --- Rule 2: exact string equality ---

test_rule2_match if {
	loan := {"actual_currency": "EUR", "expected_currency": "EUR"}
	compliance.rule2_result(loan).pass
}

test_rule2_mismatch if {
	loan := {"actual_currency": "USD", "expected_currency": "EUR"}
	not compliance.rule2_result(loan).pass
}

# --- Rule 3: `>=`, exactly-on PASSES (opposite boundary to Rule 1) ---

test_rule3_exactly_50_passes if {
	loan := {"asset_value": 500, "loan_value": 1000}
	compliance.rule3_result(loan).pass
}

test_rule3_just_under_fails if {
	loan := {"asset_value": 499.99, "loan_value": 1000}
	not compliance.rule3_result(loan).pass
}

test_rule3_well_over_passes if {
	loan := {"asset_value": 900, "loan_value": 1000}
	compliance.rule3_result(loan).pass
}

# --- Multi-fail and batch integrity, via the aggregator ---

test_multi_fail_loan_flags_both if {
	input_doc := {"loans": [{
		"loan_id": "L9",
		"loan_value_eur": 100000,
		"actual_currency": "USD",
		"expected_currency": "EUR",
		"asset_value": 100,
		"loan_value": 1000,
	}]}
	r := compliance.results with input as input_doc
	not r.L9.rule2.pass
	not r.L9.rule3.pass
	r.L9.rule1.pass
}

test_batch_integrity_keys_by_loan_id if {
	input_doc := {"loans": [
		{
			"loan_id": "A", "loan_value_eur": 30000,
			"actual_currency": "EUR", "expected_currency": "EUR",
			"asset_value": 600, "loan_value": 1000,
		},
		{
			"loan_id": "B", "loan_value_eur": 10000,
			"actual_currency": "USD", "expected_currency": "EUR",
			"asset_value": 400, "loan_value": 1000,
		},
		{
			"loan_id": "C", "loan_value_eur": 50000,
			"actual_currency": "GBP", "expected_currency": "GBP",
			"asset_value": 900, "loan_value": 1000,
		},
	]}
	r := compliance.results with input as input_doc
	r.A.rule1.pass
	r.A.rule2.pass
	r.A.rule3.pass
	not r.B.rule1.pass
	not r.B.rule2.pass
	not r.B.rule3.pass
	r.C.rule1.pass
	r.C.rule2.pass
	r.C.rule3.pass
}
