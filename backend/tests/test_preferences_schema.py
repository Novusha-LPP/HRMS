"""Palette validation can be checked without a database connection."""

import pytest
from pydantic import ValidationError

from hrms.modules.preferences.schemas import Preferences, PreferencesUpdate


@pytest.mark.parametrize("color_theme", ["classic-teal", "midnight-blue", "ember-sand"])
def test_registered_palettes_validate_and_preserve_independent_dashboard_style(color_theme):
    saved = Preferences(color_theme=color_theme, dashboard_style="overview")
    assert Preferences.model_validate_json(saved.model_dump_json()) == saved
    patch = PreferencesUpdate(dashboard_style="widgets")
    updated = saved.model_copy(update=patch.model_dump(exclude_none=True))
    assert updated.color_theme == color_theme
    assert updated.dashboard_style == "widgets"


@pytest.mark.parametrize("model", [Preferences, PreferencesUpdate])
@pytest.mark.parametrize("color_theme", ["neon", "default", "hrms-dashboard", 3])
def test_unknown_palette_ids_remain_invalid(model, color_theme):
    with pytest.raises(ValidationError):
        model(color_theme=color_theme)
