from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class DashboardLayout(SQLModel, table=True):
    """
    One person's arrangement of one dashboard: which widgets, in what order, at what size.

    `widgets` is `[{"widget": <id from dashboard/widgets.py>, "size": <one of SIZES>}]`.
    No row means the person hasn't customised it and sees the default layout. Rows belong to
    the user account; nobody reads or writes another person's layout.
    """

    __tablename__ = "dashboard_layouts"

    tenant_id: UUID = Field(primary_key=True)
    id: UUID = Field(primary_key=True)
    user_account_id: UUID = Field()
    dashboard: str = Field(max_length=30)
    widgets: list[dict[str, Any]] = Field(sa_column=Column("widgets", JSONB, nullable=False))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
