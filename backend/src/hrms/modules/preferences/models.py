from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class UserPreference(SQLModel, table=True):
    """
    How one person wants the app to look and their dashboard to work. Two independent
    choices — any combination is valid: the colour theme applies to the whole app, the
    dashboard style only to the HR/admin dashboard. No row means the defaults.
    """

    __tablename__ = "user_preferences"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    user_account_id: UUID = Field()
    color_theme: str = Field(default="classic-teal", max_length=30)
    dashboard_style: str = Field(default="widgets", max_length=30)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
