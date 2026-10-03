from typing import Literal

from pydantic import BaseModel, Field

WidgetSize = Literal["quarter", "third", "half", "full"]


class LayoutItem(BaseModel):
    widget: str = Field(max_length=60)
    size: WidgetSize


class LayoutUpdate(BaseModel):
    widgets: list[LayoutItem] = Field(max_length=30)


class WidgetInfo(BaseModel):
    id: str
    title: str
    description: str
    category: str
    default_size: WidgetSize
    sizes: list[WidgetSize]


class LayoutResponse(BaseModel):
    dashboard: str
    widgets: list[LayoutItem]
    # True when this is the default arrangement (the person never saved their own).
    is_default: bool
    # Comma-separated sections to pass to GET /v1/dashboard/hr for exactly these widgets.
    sections: str
    # Every widget this person may place, for the "add widget" picker.
    catalog: list[WidgetInfo]
