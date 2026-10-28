"""
Unit tests, no database, for marking through a connected app: the `marking` switch in the app's
settings, the session route list, the company filter on the marking sheet and what /auth/me tells
the app. The end-to-end paths are in test_integrations_sessions.py.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hrms.core.authn import Principal
from hrms.modules.integrations import profiles
from hrms.modules.integrations.catalog import (
    IntegrationSettings,
    SelfServiceSettings,
    defaults_for,
    merge,
    validate_full,
)
from hrms.modules.integrations.session_policy import SESSION_ROUTES, route_features
from hrms.modules.kernel.auth import router as auth_router
from hrms.modules.time import marking

MARKING_ROUTES = [
    ("GET", "/v1/time/marking"),
    ("PUT", "/v1/time/marking/2026-10-27"),
    ("GET", "/v1/time/marking/leave-types"),
    ("POST", "/v1/time/marking/leave"),
]


def _principal(*, via_key=True, employment_id=None):
    return Principal(
        tenant_id=uuid4(),
        user_account_id=uuid4(),
        employment_id=employment_id or uuid4(),
        role_names=frozenset({"EMPLOYEE"}),
        via_key_id=uuid4() if via_key else None,
        via_app="ERP" if via_key else None,
    )


def _settings(marking: bool) -> IntegrationSettings:
    document = IntegrationSettings().model_dump()
    document["self_service"]["marking"] = marking
    return validate_full(document)


def _rows(*rows):
    """A session.execute result whose .one_or_none() / .scalars() give these rows."""
    result = MagicMock()
    result.one_or_none.return_value = rows[0] if rows else None
    result.scalars.return_value = iter(rows)
    return result


# ─── The switch ───────────────────────────────────────────────────────────────


def test_marking_is_off_by_default_for_every_kind_of_app():
    assert SelfServiceSettings().marking is False
    for kind in ("TWO_WAY", "RECEIVE_ONLY", "READ_ONLY"):
        assert defaults_for(kind)["self_service"]["marking"] is False


def test_settings_published_before_the_switch_existed_read_as_off():
    document = IntegrationSettings().model_dump()
    del document["self_service"]["marking"]
    assert validate_full(document).self_service.marking is False


def test_a_company_override_can_switch_marking_on_or_off_alone():
    base = _settings(True).model_dump()
    off = validate_full(merge(base, {"self_service": {"marking": False}}))
    assert off.self_service.marking is False
    # The rest of self-service is untouched by the override.
    assert off.self_service.punch is True
    unrelated = validate_full(merge(base, {"self_service": {"punch": False}}))
    assert unrelated.self_service.marking is True


def test_a_misspelt_feature_is_refused_not_ignored():
    document = IntegrationSettings().model_dump()
    document["self_service"]["markng"] = True
    with pytest.raises(ValidationError):
        validate_full(document)


# ─── Which routes a session may call ──────────────────────────────────────────


@pytest.mark.parametrize(("method", "path"), MARKING_ROUTES)
def test_each_marking_route_is_open_only_through_the_marking_switch(method, path):
    assert route_features(method, path) == (True, ("marking",))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", "/v1/time/marking/2026-10-27"),  # no such call; never opened
        ("POST", "/v1/time/marking"),
        ("GET", "/v1/time/attendance-groups"),  # managing groups stays in HRMS
        ("POST", "/v1/time/attendance-groups/agrp_x/members"),
        ("PUT", "/v1/time/attendance-groups/agrp_x/access/usr_x"),
        ("GET", "/v1/time/marking/2026-10-27/extra"),
    ],
)
def test_nothing_else_about_groups_is_open_to_an_app(method, path):
    assert route_features(method, path) == (False, None)


def test_no_other_feature_opens_a_marking_route():
    for (_, path), features in SESSION_ROUTES.items():
        if path.startswith("/v1/time/marking"):
            assert features == ("marking",), path
        else:
            assert "marking" not in (features or ()), path


# ─── Which companies an app may mark ──────────────────────────────────────────


async def test_no_key_means_no_company(monkeypatch):
    session = MagicMock(execute=AsyncMock(return_value=_rows()))
    assert await profiles.app_marking_entities(session, uuid4(), uuid4()) == []


async def test_a_key_for_every_company_marks_those_that_switch_it_on(monkeypatch):
    on, off = uuid4(), uuid4()
    key = SimpleNamespace(app_id=uuid4(), legal_entity_ids=None)
    session = MagicMock(execute=AsyncMock(side_effect=[_rows(key), _rows(on, off)]))
    seen = []

    async def settings_for(_session, _tid, app_id, legal_entity_id):
        seen.append((app_id, legal_entity_id))
        return _settings(legal_entity_id == on)

    monkeypatch.setattr(profiles, "effective_settings", settings_for)
    assert await profiles.app_marking_entities(session, uuid4(), uuid4()) == [on]
    # Each company is judged by its own settings for this key's app.
    assert seen == [(key.app_id, on), (key.app_id, off)]


async def test_a_limited_key_never_reaches_a_company_it_doesnt_cover(monkeypatch):
    covered, outside = uuid4(), uuid4()
    # The key's companies are stored as JSON strings.
    key = SimpleNamespace(app_id=uuid4(), legal_entity_ids=[str(covered)])
    session = MagicMock(execute=AsyncMock(side_effect=[_rows(key), _rows(covered, outside)]))
    asked = []

    async def settings_for(_session, _tid, _app, legal_entity_id):
        asked.append(legal_entity_id)
        return _settings(True)

    monkeypatch.setattr(profiles, "effective_settings", settings_for)
    assert await profiles.app_marking_entities(session, uuid4(), uuid4()) == [covered]
    assert asked == [covered]  # the uncovered company's settings aren't even read


async def test_a_key_limited_to_no_company_marks_nobody(monkeypatch):
    key = SimpleNamespace(app_id=uuid4(), legal_entity_ids=[])
    session = MagicMock(execute=AsyncMock(side_effect=[_rows(key), _rows(uuid4())]))
    monkeypatch.setattr(profiles, "effective_settings", AsyncMock(return_value=_settings(True)))
    assert await profiles.app_marking_entities(session, uuid4(), uuid4()) == []


# ─── Is the feature on for this session ───────────────────────────────────────


async def test_feature_check_uses_the_markers_company(monkeypatch):
    company, app_id = uuid4(), uuid4()
    session = MagicMock(
        execute=AsyncMock(
            return_value=_rows(SimpleNamespace(app_id=app_id, legal_entity_id=company))
        )
    )
    settings_for = AsyncMock(return_value=_settings(True))
    monkeypatch.setattr(profiles, "effective_settings", settings_for)
    assert await profiles.app_session_feature_on(session, uuid4(), uuid4(), uuid4(), "marking")
    assert settings_for.await_args.args[2:] == (app_id, company)
    settings_for.return_value = _settings(False)
    assert not await profiles.app_session_feature_on(session, uuid4(), uuid4(), uuid4(), "marking")


async def test_feature_check_for_an_unknown_key_is_off():
    session = MagicMock(execute=AsyncMock(return_value=_rows()))
    assert not await profiles.app_session_feature_on(session, uuid4(), uuid4(), None, "marking")


# ─── What /auth/me tells the app ──────────────────────────────────────────────


async def _me(monkeypatch, principal, *, feature_on):
    built = SimpleNamespace(
        mfa_required=False,
        permissions=["attendance.view", "attendance.mark", "leave.apply", "time.punch"],
    )
    monkeypatch.setattr(auth_router, "resolve_scope", AsyncMock())
    monkeypatch.setattr(auth_router, "_build_me_response", AsyncMock(return_value=built))
    check = AsyncMock(return_value=feature_on)
    monkeypatch.setattr(profiles, "app_session_feature_on", check)
    result = await auth_router.me(principal, MagicMock())
    return set(result.permissions), check


async def test_me_hides_marking_from_an_app_that_cant_mark(monkeypatch):
    permissions, _ = await _me(monkeypatch, _principal(), feature_on=False)
    assert permissions == {"leave.apply", "time.punch"}


async def test_me_keeps_marking_for_an_app_that_can(monkeypatch):
    principal = _principal()
    permissions, check = await _me(monkeypatch, principal, feature_on=True)
    assert {"attendance.view", "attendance.mark"} <= permissions
    assert check.await_args.args[1:] == (
        principal.tenant_id,
        principal.via_key_id,
        principal.employment_id,
        "marking",
    )


async def test_me_for_an_ordinary_sign_in_doesnt_ask_about_apps(monkeypatch):
    permissions, check = await _me(monkeypatch, _principal(via_key=False), feature_on=False)
    assert {"attendance.view", "attendance.mark"} <= permissions
    check.assert_not_awaited()


# ─── The marking sheet's company filter ───────────────────────────────────────


async def _people_query(monkeypatch, principal, entities):
    group = uuid4()
    monkeypatch.setattr(marking, "access_levels", AsyncMock(return_value={group: "MARK"}))
    monkeypatch.setattr(marking, "can_manage", lambda scope: False)
    allowed = AsyncMock(return_value=entities)
    monkeypatch.setattr(profiles, "app_marking_entities", allowed)
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = MagicMock(execute=AsyncMock(return_value=result))
    people = await marking._people(
        session, principal.tenant_id, principal, MagicMock(), date(2026, 10, 27)
    )
    sql, params = session.execute.await_args.args
    return people, str(sql), params, allowed


async def test_sheet_through_an_app_is_limited_to_the_apps_companies(monkeypatch):
    company = uuid4()
    principal = _principal()
    people, sql, params, allowed = await _people_query(monkeypatch, principal, [company])
    assert people == []
    assert "e.legal_entity_id = ANY(:app_entities)" in sql
    assert params["app_entities"] == [company]
    assert allowed.await_args.args[1:] == (principal.tenant_id, principal.via_key_id)


async def test_sheet_through_an_app_with_no_company_lists_nobody(monkeypatch):
    _, sql, params, _ = await _people_query(monkeypatch, _principal(), [])
    # An empty list matches nothing, so the sheet is empty rather than unfiltered.
    assert "ANY(:app_entities)" in sql and params["app_entities"] == []


async def test_sheet_in_hrms_has_no_app_filter(monkeypatch):
    _, sql, params, allowed = await _people_query(monkeypatch, _principal(via_key=False), [])
    assert "app_entities" not in sql and "app_entities" not in params
    allowed.assert_not_awaited()
