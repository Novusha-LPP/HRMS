"""Allow the Ember Sand colour palette without changing existing preferences.

Revision ID: 0049
Revises: 0048
"""

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_user_preferences_theme", "user_preferences", type_="check")
    op.create_check_constraint(
        "ck_user_preferences_theme",
        "user_preferences",
        "color_theme IN ('classic-teal', 'midnight-blue', 'ember-sand')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_preferences_theme", "user_preferences", type_="check")
    # As in 0028, lift forced RLS for the table owner while converting every tenant's rows.
    op.execute("ALTER TABLE user_preferences NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE user_preferences SET color_theme = 'classic-teal' WHERE color_theme = 'ember-sand'"
    )
    op.execute("ALTER TABLE user_preferences FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        "ck_user_preferences_theme",
        "user_preferences",
        "color_theme IN ('classic-teal', 'midnight-blue')",
    )
