"""Reminder dates and wording: pure functions, no database."""

from datetime import date

import pytest

from hrms.modules.reminders import dates, templates


def test_presets_fill_the_offsets():
    assert dates.offsets_for("SAME_DAY", 0) == {0}
    assert dates.offsets_for("ONE_DAY_BEFORE", 0) == {1}
    assert dates.offsets_for("CONTINUOUS", 3) == {0, 1, 2, 3}
    # every second day counting back from 5, and always the day itself
    assert dates.offsets_for("ALTERNATE_DAYS", 5) == {5, 3, 1, 0}
    assert dates.offsets_for("ALTERNATE_DAYS", 4) == {4, 2, 0}
    assert dates.offsets_for("CUSTOM", 0, [7, 1, 0, 99, -2]) == {7, 1, 0}
    with pytest.raises(ValueError):
        dates.offsets_for("WEEKLY", 0)


def test_next_occurrence_rolls_into_next_year_and_handles_29_february():
    born = date(1990, 3, 15)
    assert dates.next_occurrence(born, date(2026, 3, 15)) == date(2026, 3, 15)
    assert dates.next_occurrence(born, date(2026, 3, 16)) == date(2027, 3, 15)
    leap = date(1992, 2, 29)
    assert dates.next_occurrence(leap, date(2026, 1, 1)) == date(2026, 2, 28)
    assert dates.next_occurrence(leap, date(2028, 1, 1)) == date(2028, 2, 29)


def test_due_looks_across_the_year_end():
    born = date(1990, 1, 2)
    assert dates.is_due(born, date(2026, 12, 30), frozenset({3}))
    assert not dates.is_due(born, date(2026, 12, 30), frozenset({2}))
    assert dates.years_at(born, dates.next_occurrence(born, date(2026, 12, 30))) == 37


def test_html_is_cut_down_to_safe_tags():
    dirty = (
        '<p style="color:red;position:fixed" onclick="x()">Hi'
        '<script>alert(1)</script><a href="javascript:alert(1)">bad</a>'
        '<a href="https://example.com">ok</a><img src="data:x"><iframe src="x"></iframe></p>'
    )
    clean = templates.sanitize_html(dirty)
    assert "script" not in clean and "onclick" not in clean and "position" not in clean
    assert "javascript:" not in clean and "iframe" not in clean and "<img" not in clean
    assert 'href="https://example.com"' in clean and "color:red" in clean


def test_unknown_and_misplaced_variables_are_refused():
    assert (
        templates.validate("Hi {first_name}", "BIRTHDAY", per_person_only=True, digest=False) == []
    )
    assert templates.validate("{birthdate}", "BIRTHDAY", per_person_only=True, digest=False)
    # years of service make no sense for a birthday
    assert templates.validate("{years}", "BIRTHDAY", per_person_only=True, digest=False)
    assert not templates.validate("{years}", "WORK_ANNIVERSARY", per_person_only=True, digest=False)
    # a digest lists several people, so a person's name belongs inside the repeat block
    assert templates.validate("{full_name}", "BIRTHDAY", per_person_only=False, digest=True)
    assert (
        templates.validate(
            "{count}: {#each}{full_name}{/each}", "BIRTHDAY", per_person_only=False, digest=True
        )
        == []
    )
    assert templates.validate("{#each}x", "BIRTHDAY", per_person_only=False, digest=True)


def test_values_are_escaped_and_the_block_repeats_per_person():
    people = [{"full_name": "A <b>&", "when": "today"}, {"full_name": "B", "when": "tomorrow"}]
    body = templates.render_team(
        "<p>{count} due</p><ul>{#each}<li>{full_name} {when}</li>{/each}</ul>",
        people,
        {"count": "2", "company_name": "X"},
        digest=True,
    )
    assert body == ("<p>2 due</p><ul><li>A &lt;b&gt;&amp; today</li><li>B tomorrow</li></ul>")
    single = templates.render_team(
        "{#each}<i>{full_name}</i>{/each}", people[:1], {"count": "1"}, digest=False
    )
    assert single == "<i>A &lt;b&gt;&amp;</i>"
    assert templates.when_text(0) == "today" and templates.when_text(1) == "tomorrow"
    assert templates.when_text(4) == "in 4 days"


@pytest.mark.parametrize("trigger", ["BIRTHDAY", "WORK_ANNIVERSARY", "NEW_JOINER", "EXIT"])
def test_every_ready_made_template_is_valid_and_renders_cleanly(trigger):
    from hrms.modules.reminders import service
    from hrms.modules.reminders.router import SAMPLE_PEOPLE

    starter = templates.DEFAULTS[trigger]
    people = [
        dict(p, **{"joining_date": p.get("joining_date", "2020-01-01")}) for p in SAMPLE_PEOPLE
    ]
    values = [service.person_values(p, trigger) for p in people]
    group = {"company_name": "Acme", "count": str(len(people))}

    # The wording is accepted as it stands, whether one mail lists everyone or not.
    for digest in (True, False):
        for text, own in (
            (starter["subject"], False),
            (starter["body_html"], False),
            (starter["employee_subject"], True),
            (starter["employee_body_html"], True),
        ):
            assert not templates.validate(
                text, trigger, per_person_only=own, digest=digest and not own
            ), text

    # The sanitiser keeps the design: nothing the template relies on is stripped.
    for key in ("body_html", "employee_body_html"):
        assert templates.sanitize_html(starter[key]) == starter[key]

    heads_up = templates.render_team(starter["body_html"], values, group, digest=True)
    own = templates.render_team(starter["employee_body_html"], values[:1], group, digest=False)
    for body in (heads_up, own):
        assert "{" not in body and "}" not in body  # every variable was filled in
    assert heads_up.count("Asha Patel") == 1 and heads_up.count("Imran Khan") == 1
    assert "Acme" in own and "Asha" in own
    # An exit or joining card shows who they report to; blank lines leave no stray punctuation.
    assert (
        " · "
        not in templates.render_team(
            starter["body_html"],
            [dict(values[0], role_line="", manager_line="")],
            group,
            digest=True,
        )
        .split("</h2>")[1]
        .split("<p")[2]
    )
