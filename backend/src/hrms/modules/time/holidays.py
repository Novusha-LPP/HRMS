"""Shared holiday applicability for attendance, registers and leave calculations."""


def holiday_scope_sql(holiday: str = "h", employee: str = ":eid") -> str:
    """
    SQL condition: holiday row `holiday` is a day off for `employee` (trusted identifiers only;
    the employee defaults to a bound UUID parameter).

    Two kinds of holiday apply:
    - general holidays — not on the holiday list and in no calendar — for everyone (or one
      legal entity, if set);
    - the holidays of the one calendar the employee follows on that date, resolved by
      holiday_calendar_for() (employee, else department, else legal entity, else company-wide
      assignment). A calendar day marked optional is not a day off.
    `holidays.calendar_id` is the older single-calendar link and still counts as membership.
    """
    return f"""(
        ({holiday}.calendar_id IS NULL AND NOT {holiday}.is_library
            AND NOT EXISTS (
                SELECT 1 FROM holiday_calendar_days gd
                WHERE gd.tenant_id = {holiday}.tenant_id AND gd.holiday_id = {holiday}.id)
            AND ({holiday}.legal_entity_id IS NULL OR {holiday}.legal_entity_id =
                (SELECT legal_entity_id FROM employments
                 WHERE tenant_id = {holiday}.tenant_id AND id = {employee})))
        OR EXISTS (
            SELECT 1 FROM (SELECT holiday_calendar_for(
                {holiday}.tenant_id, {employee}, {holiday}.holiday_date) AS id) cal
            WHERE cal.id IS NOT NULL AND (
                {holiday}.calendar_id = cal.id
                OR EXISTS (
                    SELECT 1 FROM holiday_calendar_days cd
                    WHERE cd.tenant_id = {holiday}.tenant_id AND cd.holiday_id = {holiday}.id
                      AND cd.calendar_id = cal.id AND NOT cd.is_optional))
        )
    )"""
