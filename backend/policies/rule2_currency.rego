# Rule 2 - Currency must match the currency of the company's HQ country.
#
# The pipeline resolves `expected_currency` via company -> PDF HQ country ->
# static country_currency.py table. This policy only compares it to the
# currency actually reported on the loan.
package compliance

import rego.v1

rule2_pass(loan) := loan.actual_currency == loan.expected_currency

rule2_result(loan) := {"pass": rule2_pass(loan), "expected": loan.expected_currency}
