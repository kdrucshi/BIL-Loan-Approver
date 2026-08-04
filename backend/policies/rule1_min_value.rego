# Rule 1 - Minimum loan value.
#
# A loan must be worth more than EUR 25,000. `loan_value_eur` has already been
# converted by the pipeline (fx.py) using the day's cached rate - this policy
# never touches the network or does currency math, only compares a number to
# a threshold. Strict `>`: exactly 25,000.00 FAILS (Evaluation_Engine.md §3).
package compliance

import rego.v1

rule1_pass(loan) := loan.loan_value_eur > 25000.00

rule1_result(loan) := {"pass": rule1_pass(loan), "threshold_eur": 25000.00}
