"""Marked attendance: groups of people (guards, drivers, cleaners…) whose days someone marks.

For people who don't punch, HR creates attendance groups and adds them. A person in a group has
each day marked present or absent by someone with access to the group, optionally with in and
out times that then count like punches; leave is recorded as a from-to range through the leave
engine. Expand only:

- attendance_groups: a tenant's groups (name, optional company, archived when retired);
- attendance_group_members: who is in which group, effective-dated (end exclusive), one group
  per person on any day;
- attendance_group_access: who may VIEW a group's sheet or MARK it, set per group from the app;
- attendance_marks: every mark, append-only — what was set (status, times), by whom, when,
  through what, and why;
- punches.source gains MARKED: times a marker entered, kept apart from the person's own punches.

Revision ID: 0074
Revises: 0073
"""

from alembic import op

from hrms.db import migration_kit as kit

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

MARKS = ("PRESENT", "ABSENT")
OLD_SOURCES = ("WEB", "MOBILE", "DEVICE", "MANUAL", "INTEGRATION")
NEW_SOURCES = (*OLD_SOURCES, "MARKED")
SOURCE_CHECK = "ck_punches_source"


def upgrade() -> None:
    for sql in kit.tenant_table(
        "attendance_groups",
        """
        name varchar(100) NOT NULL,
        description varchar(500),
        legal_entity_id uuid,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        version integer NOT NULL DEFAULT 0,
        archived_at timestamptz
        """,
        comment=(
            "Groups of people whose attendance is marked, not punched (guards, drivers, "
            "cleaners): a name, optionally the one company it belongs to, retired by archiving."
        ),
        references={"legal_entity_id": "legal_entities", "created_by": "user_accounts"},
    ):
        op.execute(sql)
    op.execute(
        kit.index(
            "attendance_groups",
            ["tenant_id", "lower(name)"],
            name="uq_attendance_groups_name",
            unique=True,
            where="archived_at IS NULL",
        )
    )

    for sql in kit.tenant_table(
        "attendance_group_members",
        """
        group_id uuid NOT NULL,
        employment_id uuid NOT NULL,
        effective_from date NOT NULL,
        effective_to date,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now()
        """,
        comment=(
            "Who is in which attendance group and from when; effective_to is the first day they "
            "are no longer in it. A person is in at most one group on any day."
        ),
        references={
            "group_id": "attendance_groups",
            "employment_id": "employments",
            "created_by": "user_accounts",
        },
    ):
        op.execute(sql)
    for sql in kit.effective_range_check("attendance_group_members"):
        op.execute(sql)
    op.execute(
        kit.no_overlap(
            "attendance_group_members",
            "ex_attendance_group_members_period",
            ["employment_id"],
            end_inclusive=False,
            deferred=True,
        )
    )

    for sql in kit.tenant_table(
        "attendance_group_access",
        f"""
        group_id uuid NOT NULL,
        user_account_id uuid NOT NULL,
        access_level varchar(10) NOT NULL,
        created_by uuid,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_attendance_group_access_level
            CHECK ({kit.check_in("access_level", ("VIEW", "MARK"))}),
        {kit.tenant_fk("attendance_group_access", "group_id", "attendance_groups")}
        """,
        comment=(
            "Who may see an attendance group's daily sheet (VIEW) or also mark it (MARK), "
            "granted per group by HR."
        ),
        # group_id's key is inline above: the unique (group, user) index below serves it.
        references={"user_account_id": "user_accounts", "created_by": "user_accounts"},
    ):
        op.execute(sql)
    op.execute(
        kit.index(
            "attendance_group_access",
            ["tenant_id", "group_id", "user_account_id"],
            name="uq_attendance_group_access_user",
            unique=True,
        )
    )

    for sql in kit.tenant_table(
        "attendance_marks",
        f"""
        employment_id uuid NOT NULL,
        work_date date NOT NULL,
        status varchar(10),
        punch_in timestamptz,
        punch_out timestamptz,
        remark varchar(500),
        source varchar(20) NOT NULL DEFAULT 'MANUAL',
        marked_by uuid NOT NULL,
        marked_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_attendance_marks_status CHECK ({kit.check_in("status", MARKS)}),
        CONSTRAINT ck_attendance_marks_source
            CHECK ({kit.check_in("source", ("MANUAL", "INTEGRATION"))}),
        CONSTRAINT ck_attendance_marks_times
            CHECK (punch_out IS NULL OR (punch_in IS NOT NULL AND punch_out > punch_in))
        """,
        comment=(
            "Every time a marked day was set or cleared: the employee and date, the status "
            "(NULL: cleared) and any in/out times set, who did it, when, through what, and why."
        ),
        references={"employment_id": "employments", "marked_by": "user_accounts"},
        append_only=True,
    ):
        op.execute(sql)

    op.execute(f"ALTER TABLE punches DROP CONSTRAINT {SOURCE_CHECK}")
    for sql in kit.add_check("punches", SOURCE_CHECK, kit.check_in("source", NEW_SOURCES)):
        op.execute(sql)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM attendance_marks)
             OR EXISTS (SELECT 1 FROM punches WHERE source = 'MARKED') THEN
            RAISE EXCEPTION 'marked attendance exists; it cannot be rolled back';
          END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE punches DROP CONSTRAINT {SOURCE_CHECK}")
    for sql in kit.add_check("punches", SOURCE_CHECK, kit.check_in("source", OLD_SOURCES)):
        op.execute(sql)
    for table in (
        "attendance_marks",
        "attendance_group_access",
        "attendance_group_members",
        "attendance_groups",
    ):
        op.execute(f"DROP TABLE {table}")
