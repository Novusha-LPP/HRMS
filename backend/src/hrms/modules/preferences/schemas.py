from typing import Literal

from pydantic import BaseModel

# Colour palette ids shared with the frontend theme registry.
ColorTheme = Literal["classic-teal", "midnight-blue", "ember-sand"]
# "widgets": the customisable widget grid; "overview": the fixed HRMS overview layout.
DashboardStyle = Literal["widgets", "overview"]


class Preferences(BaseModel):
    color_theme: ColorTheme = "classic-teal"
    dashboard_style: DashboardStyle = "widgets"


class PreferencesUpdate(BaseModel):
    """Only the fields sent are changed."""

    color_theme: ColorTheme | None = None
    dashboard_style: DashboardStyle | None = None
