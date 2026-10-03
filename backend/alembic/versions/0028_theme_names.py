"""Give the colour themes proper ids: classic-teal and midnight-blue

They were stored as 'default' and 'hrms-dashboard', which leaked into what people saw
(e.g. in browser storage). Existing choices are converted, so nobody's theme changes.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

RENAMES = {"default": "classic-teal", "hrms-dashboard": "midnight-blue"}


def _switch(mapping: dict[str, str], default: str) -> None:
    op.drop_constraint("ck_user_preferences_theme", "user_preferences", type_="check")
    # Every tenant's rows: the table forces RLS even on its owner, so lift that just for this.
    op.execute("ALTER TABLE user_preferences NO FORCE ROW LEVEL SECURITY")
    for old, new in mapping.items():
        op.execute(f"UPDATE user_preferences SET color_theme = '{new}' WHERE color_theme = '{old}'")
    op.execute("ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY")
    op.alter_column("user_preferences", "color_theme", server_default=default)
    allowed = ", ".join(f"'{v}'" for v in mapping.values())
    op.create_check_constraint(
        "ck_user_preferences_theme", "user_preferences", f"color_theme IN ({allowed})"
    )


def upgrade() -> None:
    _switch(RENAMES, "classic-teal")


def downgrade() -> None:
    _switch({new: old for old, new in RENAMES.items()}, "default")
