"""Endpoint docs: Payroll."""

DOCS: dict[str, tuple[str, str]] = {
    # ─── Statutory rules ─────────────────────────────────────────────────────
    "list_statutory_rules": (
        "List statutory values",
        """
The statutory values payroll calculates with: PF and ESIC rates and wage ceilings, and whether
PF contributions stop at the ceiling. Each value applies from `effective_from` until
`effective_to` (exclusive; `null` = still in force) and says where it came from (`source`).

`verified` is `false` until someone with `payroll.review`, other than the person who entered
it, has checked it against the official notification. A breakup built on an unverified value is
marked `provisional`. Values that were replaced stay listed; `include_retired=true` also shows
withdrawn ones.
""",
    ),
    "load_india_statutory_defaults": (
        "Load the India statutory defaults",
        """
Adds the platform's India values (PF 12% / 12% on a ₹15,000 ceiling, EPS 8.33%, ESIC 0.75% /
3.25% on a ₹21,000 ceiling) for every rule the company hasn't set yet. They load **unverified**:
the payroll reviewer must check each against the current EPFO and ESIC notifications. Rules the
company already maintains are left alone, so calling this twice changes nothing.
""",
    ),
    "create_statutory_rule": (
        "Record a new statutory value from a date",
        """
Records a new value for a rule (`rule_code`, for example `ESIC_WAGE_CEILING`) from
`effective_from`. The value in force until then ends that day, so past payroll keeps the value it
used. `source` is the notification or circular the value comes from. The new value starts
unverified.

A date on or before the current value's start is refused (`409`). Percentages can't exceed 100.
""",
    ),
    "verify_statutory_rule": (
        "Verify a statutory value",
        "Marks a value as checked against its official source. Needs `payroll.review`, and the "
        "person who entered the value can't verify it (`403`). Verifying twice changes nothing.",
    ),
    # ─── Components ──────────────────────────────────────────────────────────
    "list_pay_components": (
        "List pay components",
        """
Everything that can appear on a payslip, in payslip order. `kind` is `EARNING`, `DEDUCTION`,
`EMPLOYER_CONTRIBUTION`, `REIMBURSEMENT` or `INFO`. `in_pf_wages` and `in_esic_wages` say whether
the component counts towards PF and ESIC wages; `prorate` whether it is reduced for unpaid days.
PF and ESIC components carry a `statutory_code` and are always calculated by law.
""",
    ),
    "create_pay_component": (
        "Create a pay component",
        """
Adds a component. `code` is unique for the company (any case) and is stored in capitals. A
`statutory_code` component must be a deduction (employee share) or an employer contribution
(employer share), and there can be only one component for each statutory code (`409`).
""",
    ),
    "create_standard_pay_components": (
        "Add the standard India pay components",
        "Adds Basic, HRA, Special allowance, and the employee and employer shares of PF and ESIC, "
        "skipping any the company already has. Returns the full list.",
    ),
    "update_pay_component": (
        "Update a pay component",
        "Changes a component's name, flags, payslip order or status. Its code, kind and "
        "statutory code can't change: create a new component instead. The change applies to "
        "breakups worked out from now on.",
    ),
    # ─── Structures ──────────────────────────────────────────────────────────
    "preview_salary_breakup": (
        "Break a CTC down with a draft structure",
        """
Works out the monthly breakup of `annual_ctc` with the given structure `lines`, without saving
anything; the structure editor uses it to show the result as HR types. `on` picks the statutory
values in force on that date (today by default).

A CTC the structure can't pay, or a structure that isn't valid, is refused (`422`) with a
message for HR.
""",
    ),
    "list_salary_structures": (
        "List salary structures",
        """
The structures in use, each with its lines in order and `employees`, the number of people whose
current salary uses this version. A line is `FIXED` (a monthly `amount`), `PERCENT` (of the
monthly CTC or of a component listed above it), `BALANCE` (what is left of the CTC; exactly one
earning) or `STATUTORY` (PF and ESIC). `legal_entity_id` limits a structure to one company;
`null` means every company.
""",
    ),
    "create_salary_structure": (
        "Create a salary structure",
        "Saves a structure. Its shape is checked: exactly one balancing earning, percentages only "
        "of the CTC or an earlier component, PF and ESIC only as statutory lines, and only active "
        "components (`422`).",
    ),
    "replace_salary_structure": (
        "Save a new version of a salary structure",
        """
Saves the edited structure as a new version with a new ID and retires the old one. Salaries
already assigned with the old version keep it, and their breakup, until they are revised; new
assignments and revisions use the new version.
""",
    ),
    "deactivate_salary_structure": (
        "Stop offering a salary structure",
        "Takes a structure out of the list so it can't be chosen for new salaries. Salaries "
        "already on it are not changed.",
    ),
    "create_standard_salary_structure": (
        "Add the standard India salary structure",
        "Adds a ready-made structure to edit: Basic 50% of CTC, HRA 40% of Basic, Special "
        "allowance as the balance, with PF and ESIC. Adds the standard components first if they "
        "are missing.",
    ),
    # ─── Employee salaries ───────────────────────────────────────────────────
    "list_salaries": (
        "List current salaries",
        "Every current employee you can see, with their annual CTC, structure and the date it "
        "applies from: the salary in force today or, if none, the next one to start (its "
        "`effective_from` is then in the future). `annual_ctc` is `null` for people without a "
        "salary. Filter by `legal_entity_id`.",
    ),
    "get_employee_compensation": (
        "An employee's salary, breakup and history",
        """
The current salary (or the next one, if the first starts in the future), its monthly breakup
with today's statutory values, and every salary the employee has had, newest first. When the
breakup can't be worked out, for example because a statutory value is missing, `breakup` is
`null` and `breakup_error` says why.
""",
    ),
    "set_employee_compensation": (
        "Assign or revise an employee's salary",
        """
Sets the annual CTC on a structure from `effective_from`. For a revision, the current salary ends
that day; history is never overwritten. Refused when:

- the date is on or before the current salary's start (`409`), or before the employee joined
  (`422`);
- the employee has left (`409`);
- the structure belongs to another company, or can't pay this CTC (`422`);
- it is your own salary (`403`).
""",
    ),
    # ─── Payslip templates ───────────────────────────────────────────────────
    "payslip_template_overview": (
        "Payslip templates",
        """
The group's payslip template (`id: null` until one is saved: the built-in default), each
company's own template (`null` when it uses the group's), and the employee `fields` a template
can print. Needs `payroll.write` or `org.write`; companies outside your scope aren't listed.
""",
    ),
    "put_group_payslip_template": (
        "Save the group's payslip template",
        """
Sets what every company's payslips show unless a company has its own template: the `layout`
(`MODERN`, `CLASSIC` or `COMPACT`, half A4), the `title`, the employee fields in order, which
blocks appear, and the signature (`COMPUTER_GENERATED` statement, or a `SIGNATORY` who signs for
every company). Needs a group-level administrator. Send the `version` you loaded.
""",
    ),
    "put_company_payslip_template": (
        "Save a company's own payslip template",
        "A complete template for one company, used instead of the group's. The signatory must "
        "sign for this company or for every company.",
    ),
    "delete_company_payslip_template": (
        "Use the group's payslip template again",
        "Removes a company's own template.",
    ),
    "preview_payslip_template": (
        "Preview a payslip template",
        """
Returns a PDF of an unsaved `template` with the branding of `legal_entity_id` (or the group's),
filled with made-up figures and watermarked SAMPLE, so designing a payslip shows nobody's pay.
`format=png` returns the pages as one image instead, for showing on screen.
""",
    ),
}
