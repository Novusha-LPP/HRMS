"""
Golden cases for the CTC breakup, worked by hand. These are the cases the payroll reviewer
(decision D-13) checks; a change to the calculator must keep them true or explain why not.

Rules used (the India pack defaults, still to be verified by each company's reviewer):
PF ceiling ₹15,000 with contributions capped at it, PF 12% employee and 12% employer;
ESIC ceiling ₹21,000, 0.75% employee and 3.25% employer.
"""

from decimal import Decimal as D

import pytest

from hrms.modules.payroll.calculator import BreakupError, Line, RuleValue, calculate

RULES = {
    "PF_WAGE_CEILING": RuleValue(D("15000"), True),
    "PF_CAP_TO_CEILING": RuleValue(D("1"), True),
    "PF_EMPLOYEE_RATE": RuleValue(D("12"), True),
    "PF_EMPLOYER_RATE": RuleValue(D("12"), True),
    "ESIC_WAGE_CEILING": RuleValue(D("21000"), True),
    "ESIC_EMPLOYEE_RATE": RuleValue(D("0.75"), True),
    "ESIC_EMPLOYER_RATE": RuleValue(D("3.25"), True),
}

STANDARD = [
    Line(
        "BASIC",
        "Basic",
        "EARNING",
        "PERCENT",
        percent=D("50"),
        base="CTC",
        in_pf_wages=True,
        in_esic_wages=True,
    ),
    Line(
        "HRA",
        "House rent allowance",
        "EARNING",
        "PERCENT",
        percent=D("40"),
        base="COMPONENT",
        base_code="BASIC",
        in_esic_wages=True,
    ),
    Line("SPECIAL", "Special allowance", "EARNING", "BALANCE", in_esic_wages=True),
    Line(
        "PF_ER", "PF (employer)", "EMPLOYER_CONTRIBUTION", "STATUTORY", statutory_code="PF_EMPLOYER"
    ),
    Line(
        "ESIC_ER",
        "ESIC (employer)",
        "EMPLOYER_CONTRIBUTION",
        "STATUTORY",
        statutory_code="ESIC_EMPLOYER",
    ),
    Line("PF_EE", "PF (employee)", "DEDUCTION", "STATUTORY", statutory_code="PF_EMPLOYEE"),
    Line("ESIC_EE", "ESIC (employee)", "DEDUCTION", "STATUTORY", statutory_code="ESIC_EMPLOYEE"),
]


def amounts(breakup):
    return {bl.code: bl.monthly for bl in breakup.lines}


def test_six_lakh_ctc_pf_capped_and_no_esic():
    b = calculate(D("600000"), STANDARD, RULES)
    a = amounts(b)
    assert b.monthly_ctc == D("50000.00")
    assert (a["BASIC"], a["HRA"]) == (D("25000.00"), D("10000.00"))
    assert a["PF_ER"] == D("1800")  # 12% of the ₹15,000 ceiling, not of the ₹25,000 basic
    assert a["ESIC_ER"] == 0 and not b.esic_applies  # gross is far over ₹21,000
    assert a["SPECIAL"] == D("13200.00")
    assert b.gross == D("48200.00")
    assert (a["PF_EE"], a["ESIC_EE"]) == (D("1800"), 0)
    assert b.net_before_tax == D("46400.00")
    assert b.gross + b.employer_contributions == b.monthly_ctc


def test_two_point_four_lakh_ctc_with_esic():
    b = calculate(D("240000"), STANDARD, RULES)
    a = amounts(b)
    assert (a["BASIC"], a["HRA"], a["PF_ER"]) == (D("10000.00"), D("4000.00"), D("1200"))
    # G + 1,200 + ceil(3.25% of G) = 20,000 gives G = 18,208 (3.25% of it is 591.76 → 592).
    assert b.esic_applies
    assert a["ESIC_ER"] == D("592")
    assert a["SPECIAL"] == D("4208.00")
    assert b.gross == D("18208.00")
    assert a["ESIC_EE"] == D("137")  # 0.75% of 18,208 = 136.56, rounded up
    assert b.net_before_tax == D("18208.00") - D("1200") - D("137")
    assert b.gross + b.employer_contributions == D("20000.00")


def test_ctc_that_does_not_divide_into_whole_rupees():
    b = calculate(D("500000"), STANDARD, RULES)
    a = amounts(b)
    assert b.monthly_ctc == D("41666.67")
    assert a["BASIC"] == D("20833.34") and a["HRA"] == D("8333.34")
    assert a["SPECIAL"] == D("10699.99")
    assert b.gross + b.employer_contributions == b.monthly_ctc


def test_basic_under_the_ceiling_uses_actual_pf_wages():
    b = calculate(D("288000"), STANDARD, RULES)  # basic 12,000 < 15,000 ceiling
    assert amounts(b)["PF_ER"] == D("1440")


def test_ctc_too_low_for_the_fixed_parts():
    lines = [
        Line("BASIC", "Basic", "EARNING", "FIXED", amount=D("25000")),
        Line("SPECIAL", "Special allowance", "EARNING", "BALANCE"),
    ]
    with pytest.raises(BreakupError, match="too low"):
        calculate(D("120000"), lines, RULES)


def test_structure_shape_is_checked():
    two_balances = [
        Line("A", "A", "EARNING", "BALANCE"),
        Line("B", "B", "EARNING", "BALANCE"),
    ]
    with pytest.raises(BreakupError, match="Exactly one"):
        calculate(D("100000"), two_balances, RULES)
    forward_reference = [
        Line(
            "HRA", "HRA", "EARNING", "PERCENT", percent=D("40"), base="COMPONENT", base_code="BASIC"
        ),
        Line("BASIC", "Basic", "EARNING", "PERCENT", percent=D("50"), base="CTC"),
        Line("SPECIAL", "Special", "EARNING", "BALANCE"),
    ]
    with pytest.raises(BreakupError, match="listed above"):
        calculate(D("100000"), forward_reference, RULES)


def test_unverified_rules_make_the_breakup_provisional():
    rules = dict(RULES, PF_EMPLOYER_RATE=RuleValue(D("12"), False))
    b = calculate(D("600000"), STANDARD, rules)
    assert b.warnings[0].startswith("Provisional")
    assert "PF_EMPLOYER_RATE" in b.warnings[0]


def test_missing_statutory_rules_are_reported_not_guessed():
    rules = {k: v for k, v in RULES.items() if not k.startswith("ESIC")}
    with pytest.raises(BreakupError, match="ESIC_WAGE_CEILING"):
        calculate(D("240000"), STANDARD, rules)
