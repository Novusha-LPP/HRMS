# Rejoin, re-hire and transfer: complete plan

Status: proposal, nothing built. Written 2026-10-21.

## What exists today (checked in the code)

- A person (`Person`) can have many employments (`Employment`), one per legal entity and spell of work.
- **Rehire** (`PersonnelActionType.REHIRE`) is allowed only for a SEPARATED employment. It reuses the same employment: state goes back to PROBATION, separation date is cleared, a new assignment is placed (`people/router.py`). The hire date is not changed.
- **Leave** balances belong to the employment, so a rehire silently continues the old balances. Separation does not lapse, encash or carry forward anything.
- **Accrual** skips people with a separation date on or before the run date and resumes after a rehire. It does not back-fill months that were skipped (`leave/router.py`, accrual docstring).
- Eligibility ("minimum service months") counts from `hire_date`, so the original hire date counts the gap and the earlier service.
- **New hire** creates a new employment for a chosen person. I saw no check that warns when that person already has a past employment.
- There is no inter-company transfer, and no record of service with an outside employer.

## The scenarios

| # | Scenario | Right behaviour |
|---|---|---|
| A | Same company, returns after a break (resigned, terminated, long absence) | Rehire; HR chooses Continue or Start fresh (see below) |
| B | Same company, returns immediately (technical resignation, same day or next day) | Rehire with Continue by default; service is continuous |
| C | Another legal entity in the same group | Inter-company transfer: close one employment, open another, carry or settle leave by company rule |
| D | Earlier employer outside the system | Hire as new; record prior service (employer, from, to, recognised or not) |
| E | Hired as a brand-new person when they already exist | Block or warn at hire: "this person has a past employment, rejoin them" |
| F | Rehire of someone whose exit was never completed | Block with a clear message: finish or cancel the exit first |

## Build steps

1. **Settlement at separation** (company setting, per leave type): lapse, encash, or carry forward to a rejoin. Each result is a ledger entry (`LAPSE`, `ENCASHMENT` or `CARRY_FORWARD`) so history stays intact. Default for existing companies: no change in behaviour.
2. **Rehire choice**: Continue (keep balances, keep original service start) or Start fresh (close old balances with a recorded lapse, start new balances from the rejoin date, restart the service start date used for eligibility). The choice is a field on the rehire request and the integration rehire endpoint, stored on the personnel action and shown in the audit trail.
3. **Company default** for step 2, so HR is asked only when they want to override.
4. **Accrual for the gap**: Continue means the gap months are not credited (current behaviour). State this on the screen so nobody expects back-pay of leave.
5. **Duplicate guard at hire** (scenario E): if the person has any past employment, require choosing Rejoin or confirming "new employment on purpose".
6. **Prior service from outside** (scenario D): a small list on the employment (employer, dates, recognised for gratuity, recognised for leave eligibility). Eligibility and gratuity read it; nothing else changes.
7. **Inter-company transfer** (scenario C): one action that separates from entity A and hires into entity B on the same day, carrying leave balances by the rule in step 1 and copying the person's documents and photo link (the person record is shared, so these already follow).
8. **Payroll and statutory**: a rejoin keeps the same UAN and ESIC IP number (they belong to the person). Payroll starts from the rejoin date; the gap has no salary. A fresh start does not reset PF or tax records.
9. **Help and docs**: add the rules to the in-app help (employee and leave topics) and `docs/FEATURES.md`.

## Tests

- Continue keeps balances and eligibility dates exactly.
- Fresh closes old balances with a lapse entry, starts new ones, restarts eligibility.
- Accrual does not credit the gap in either case.
- Rehire is refused unless SEPARATED; double rehire is refused.
- Duplicate guard catches the same person across entities.
- Transfer between entities carries or settles leave as configured and leaves exactly one active employment.
- Integration rehire accepts the choice and rejects unknown values.

## Open decisions for the user

1. On Start fresh, does the service start date for leave eligibility restart, or only the balances?
2. Default behaviour per company: Continue or Start fresh?
3. At separation, what should happen to unused leave by default: lapse, encash, or hold for a possible rejoin?
4. Should the gap longer than some number of days force Start fresh?
5. Do you need group transfers (C) and outside prior service (D) now, or after A, B, E, F?

## Notes

- Indian law has no single rule here; gratuity continuity depends on whether earlier dues were settled, and leave depends on company policy. The design keeps both as company choices rather than hard-coding a rule. Confirm statutory points (the Code on Social Security replacing the Payment of Gratuity Act) with a labour lawyer.

## Research findings (2026-10-21)

Sources are listed at the end. Status: **Supported** = stated by an official or primary-looking page; **Secondary** = law-firm, news or vendor commentary only; **Open** = nothing reliable found.

| Topic | Finding | Status |
|---|---|---|
| Labour codes in force | The four Labour Codes were notified to take effect on 21 November 2025. Some provisions wait for central rules (draft rules issued 30 Dec 2025). | Supported (law-firm and government summaries); confirm each provision in the Gazette |
| Continuous service | Code on Social Security s.54: service counts as continuous despite sickness, leave, lay-off, strike and unauthorised absence (unless the employer formally treats it as a break). A separate deemed-continuity test applies (240 or 190 days in 12 months; 75% for seasonal). | Supported by statute text summaries; read s.54 itself before quoting |
| Gratuity | s.53: payable after 5 years of continuous service, waived for death, disablement and fixed-term expiry. 15 days' wages per completed year; more than 6 months counts as a year. | Supported; the "1 year for fixed-term" figure is Secondary |
| Resignation and rejoin | Continuity is usually not preserved after resignation unless the resignation was withdrawn or the employer grants continuity. A Dec 2025 Supreme Court ruling (DTC) held that resignation forfeits past service for pension but gratuity after 5 years is still payable. | Secondary for rejoin; the ruling itself should be read |
| Leave on exit (OSH Code) | Accrued annual leave is payable as wages on discharge, resignation, superannuation or death (proportionate even under 180 days), within 2 days of leaving. Carry-forward cap 30 days. Eligibility 180 days; 1 day per 20 worked. Applies to "workers" as the Code defines them. | Secondary; whether it overrides state Shops Acts is unsettled |
| Leave on rejoin | No statute or ruling found that fixes what happens to leave on a rejoin. State Shops Acts preserve earlier accrued leave in transition cases but say nothing specific on rejoin. | Open: company policy |
| PF / UAN | A rejoin reuses the member's UAN; a second UAN appears only when the old one is not given or the old exit date was never filed. The date of exit must be updated before an online transfer, and can be updated only after two months of leaving. EPF Scheme para 57(2) allows transfer of the old balance. | Supported by EPFO FAQ; procedural details Secondary |

## What the research changes in the plan

1. **Record the decision.** Continuity after a resignation is a decision, not a default. "Continue" must store who approved it, why, and the dates of the break. The audit trail already holds the personnel action; add the reason as required text.
2. **Settle leave at exit, then do not double count.** Where the OSH Code applies, unused leave is paid out at exit. If it was paid, "Continue" must not restore it. The rejoin screen shows what was encashed or lapsed at separation, and Continue restores only what was held.
3. **Gratuity restarts when it was paid.** Show "gratuity paid at exit: yes/no" on the rejoin screen. If yes, service for gratuity restarts; if no, HR records whether the break is condoned.
4. **UAN.** Keep the UAN on the person, never create a second one on rejoin, and show a reminder that the earlier exit date must be filed (and that online transfer opens two months after leaving).
5. **Company policy stays configurable.** Because leave on rejoin has no fixed rule, keep the defaults per company and keep legal wording out of the screens until each claim is checked against the Gazette.

## Sources

- Code on Social Security 2020, s.53 and s.54: https://www.advocatekhoj.com/library/bareacts/codeonsocialsecurity/53.php , https://indiankanoon.org/doc/4645270/ , https://www.indiacode.nic.in/bitstream/123456789/16823/1/aA2020-36.pdf
- Labour Codes commencement: https://www.legal500.com/intelligence/india/employment-and-hr/central-government-notifies-commencement-of-all-four-labour-codes-%E2%80%93-effective-21-november-2025 , https://www.pib.gov.in/PressReleasePage.aspx?PRID=2209767&reg=48&lang=2
- EPFO transfer claim FAQ: https://www.epfindia.gov.in/site_docs/PDFs/Circulars/Y2020-2021/faq_transfer_claim.pdf ; EPF Scheme 1952: https://indiankanoon.org/doc/6550002/
- OSH Code leave: https://www.outlookmoney.com/news/new-labour-codes-change-heres-how-you-earn-carry-and-encash-leave , https://acuitylaw.co.in/faqs/faqs-on-the-occupational-safety-health-and-working-conditions-code-2020-and-the-occupational-safety-health-and-working-conditions-central-rules-2026/
- Resignation, gratuity and continuity: https://www.indialaw.in/blog/labour/pension-gratuity-supreme-court/ , https://www.livelaw.in/supreme-court/employees-who-resigned-or-retired-after-5-years-service-entitled-to-gratuity-supreme-court-312782
