"""
The wording of a reminder mail: variables, a safe subset of HTML, and the email layout.

HR edits the middle of the mail in a rich-text editor, which produces HTML. Three things keep
that safe and predictable:

- `sanitize_html` keeps only a small allow-list of tags, attributes and style properties, so
  a pasted script, form or tracking pixel never reaches a recipient.
- `{variable}` values are HTML-escaped when filled in, so a name like `O'Brien & <Sons>` cannot
  break the layout. An unknown variable is refused when the rule is saved (`validate`), so a
  literal `{birthdate}` can never go out.
- `wrap` puts the body in a fixed table layout with inline styles (the only thing Outlook
  renders reliably), headed by the company name in its brand colour.

A team mail can repeat one block per person:  {#each} ... {/each}.  Outside the block only the
group variables (`{count}`, `{company_name}`) are available.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

TOKEN = re.compile(r"\{([a-z_]+)\}")
EACH = re.compile(r"\{#each\}(.*?)\{/each\}", re.S)
MAX_BODY = 20_000

PERSON_VARIABLES: dict[str, str] = {
    "first_name": "First name",
    "full_name": "Full name",
    "department": "Department",
    "designation": "Job title",
    "role_line": "Job title and department together, e.g. Executive · Sales",
    "manager_line": "“Reports to …”, or nothing when there is no manager",
    "manager_name": "Manager's name",
    "event_date": "Date of the birthday or anniversary, e.g. 14 Nov",
    "days_left": "Days until the day, 0 on the day itself",
    "when": "today, tomorrow, or in 3 days",
}
TRIGGER_VARIABLES: dict[str, dict[str, str]] = {
    "BIRTHDAY": {"age": "Age they turn"},
    "WORK_ANNIVERSARY": {"years": "Years of service", "joining_date": "Date of joining"},
    "NEW_JOINER": {"joining_date": "Date of joining"},
    "EXIT": {"last_day": "Last working day"},
}
GROUP_VARIABLES: dict[str, str] = {
    "company_name": "Company name",
    "count": "How many people are in this mail",
}


def variables_for(trigger: str) -> dict[str, str]:
    return {**PERSON_VARIABLES, **TRIGGER_VARIABLES[trigger], **GROUP_VARIABLES}


# ── Safe HTML ───────────────────────────────────────────────────────────────────────────────

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "a", "ul", "ol", "li", "h1", "h2", "h3",
    "table", "thead", "tbody", "tr", "td", "th", "div", "span", "hr", "img",
}  # fmt: skip
VOID = {"br", "hr", "img"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "form", "head", "title"}
ALLOWED_ATTRS = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align"},
}
ALLOWED_STYLE = {
    "color", "background-color", "font-size", "font-weight", "font-style", "text-align",
    "text-decoration", "padding", "margin", "border", "border-radius", "width", "line-height",
}  # fmt: skip
SAFE_URL = re.compile(r"^(https?://|mailto:)", re.I)
SAFE_STYLE_VALUE = re.compile(r"^[#\w\s.,%()\-]+$")


def _clean_style(value: str) -> str:
    kept = []
    for declaration in value.split(";"):
        name, _, setting = declaration.partition(":")
        name, setting = name.strip().lower(), setting.strip()
        if name in ALLOWED_STYLE and setting and SAFE_STYLE_VALUE.match(setting):
            kept.append(f"{name}:{setting}")
    return ";".join(kept)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skipping = 0
        self.open: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skipping += 1
            return
        if self.skipping or tag not in ALLOWED_TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ""
            if name == "style":
                if cleaned := _clean_style(value):
                    kept.append(f'style="{html.escape(cleaned)}"')
            elif name in ALLOWED_ATTRS.get(tag, ()):
                if name in {"href", "src"} and not SAFE_URL.match(value.strip()):
                    continue
                kept.append(f'{name}="{html.escape(value, quote=True)}"')
        if tag == "img" and not any(k.startswith("src=") for k in kept):
            return
        if tag == "a":
            kept.append('rel="noopener noreferrer"')
        self.out.append(f"<{tag}{' ' + ' '.join(kept) if kept else ''}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping or tag not in ALLOWED_TAGS or tag in VOID:
            return
        if tag in self.open:  # close anything left open inside it first
            while (last := self.open.pop()) != tag:
                self.out.append(f"</{last}>")
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(html.escape(data, quote=False))

    def close(self):
        super().close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")


def sanitize_html(raw: str) -> str:
    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return "".join(parser.out).strip()


# ── Variables ───────────────────────────────────────────────────────────────────────────────


def validate(text: str, trigger: str, *, per_person_only: bool, digest: bool) -> list[str]:
    """Problems with a subject or body: unknown variables, a misplaced repeat block. Empty
    when it is fine. `per_person_only` is the employee mail (one person, no repeat block)."""
    problems: list[str] = []
    allowed = variables_for(trigger)
    opens, closes = text.count("{#each}"), text.count("{/each}")
    if per_person_only and (opens or closes):
        problems.append("The repeat block {#each} is only for the team mail.")
    elif opens != closes or opens > 1 or (opens and not EACH.search(text)):
        problems.append("Use one {#each} ... {/each} block, opened before it is closed.")
    outside = EACH.sub(" ", text)
    for name in sorted(set(TOKEN.findall(text))):
        if name not in allowed:
            problems.append(f"Unknown variable {{{name}}}.")
    if digest and not per_person_only:
        for name in sorted(set(TOKEN.findall(outside))):
            if name in allowed and name not in GROUP_VARIABLES:
                problems.append(
                    f"{{{name}}} is about one person: use it between {{#each}} and {{/each}} "
                    "when the mail lists several people."
                )
    return problems


def fill(text: str, values: dict[str, str], *, escape: bool) -> str:
    def replace(match: re.Match) -> str:
        value = values.get(match.group(1))
        if value is None:
            return ""
        return html.escape(value) if escape else value

    return TOKEN.sub(replace, text)


def render_team(
    body_html: str,
    people: list[dict[str, str]],
    group: dict[str, str],
    *,
    digest: bool,
) -> str:
    """The team body for these people. A digest fills the repeat block once per person (or the
    whole body, when there is no block, once for the first); a per-person mail is rendered
    for one person."""
    body = sanitize_html(body_html)
    if digest:
        block = EACH.search(body)
        if block:
            rows = "".join(fill(block.group(1), {**group, **p}, escape=True) for p in people)
            body = body[: block.start()] + rows + body[block.end() :]
            return fill(body, group, escape=True)
    person = people[0] if people else {}
    body = EACH.sub(lambda m: m.group(1), body)
    return fill(body, {**group, **person}, escape=True)


def when_text(days_left: int) -> str:
    if days_left == 0:
        return "today"
    return "tomorrow" if days_left == 1 else f"in {days_left} days"


# ── Layout and plain text ───────────────────────────────────────────────────────────────────


def wrap(body: str, *, company: str, color: str, on_color: str, footer: str | None) -> str:
    note = footer or f"This is an automated message from {company}."
    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#f3f4f6;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f3f4f6"><tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;background:#ffffff;border-radius:10px;'
        'border:1px solid #e5e7eb">'
        f'<tr><td style="background:{color};color:{on_color};padding:22px 28px;'
        'border-radius:10px 10px 0 0;font-size:19px;font-weight:bold;letter-spacing:0.2px">'
        f"{html.escape(company)}</td></tr>"
        '<tr><td style="padding:28px;font-size:15px;line-height:1.6;color:#111827">'
        f"{body}</td></tr>"
        '<tr><td style="padding:16px 28px;font-size:12px;line-height:1.5;color:#6b7280;'
        f'border-top:1px solid #e5e7eb">{html.escape(note)}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def to_text(body_html: str) -> str:
    text = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (\1)", body_html, flags=re.S)
    text = re.sub(r"</(p|div|h[1-3]|tr|li|table)>|<br\s*/?>|<hr\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


# ── Starter wording for a new rule ──────────────────────────────────────────────────────────
# Built from a few blocks so the four events look alike. Only tags and styles that sanitize_html
# keeps are used, so what HR sees in the editor is what is mailed.

MUTED = "color:#6b7280;font-size:13px"
CARD = (
    '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;'
    'margin:0 0 10px;background-color:#f9fafb">'
)


def _heads_up(emoji: str, title: str, intro: str, lines: str, closing: str) -> str:
    """A heading, a short intro, one card per person (repeated), and a sign-off."""
    return (
        f'<p style="margin:0;font-size:34px">{emoji}</p>'
        f'<h2 style="margin:6px 0 4px;font-size:21px">{title}</h2>'
        f'<p style="margin:0 0 18px;{MUTED}">{intro}</p>'
        "{#each}"
        f"{CARD}"
        '<p style="margin:0;font-size:16px;font-weight:bold">{full_name}</p>'
        f'<p style="margin:2px 0 0;{MUTED}">{{role_line}}</p>'
        f"{lines}</div>"
        "{/each}"
        f'<p style="margin:18px 0 0;{MUTED}">{closing}</p>'
    )


def _greeting(emoji: str, headline: str, message: str) -> str:
    """A centred personal message."""
    return (
        f'<p style="margin:0;text-align:center;font-size:48px">{emoji}</p>'
        f'<h1 style="margin:8px 0 16px;text-align:center;font-size:25px">{headline}</h1>'
        f'<p style="margin:0 0 10px;text-align:center">{message}</p>'
        f'<p style="margin:22px 0 0;text-align:center;{MUTED}">'
        "With warm wishes,<br>{company_name}</p>"
    )


def _line(text: str) -> str:
    return f'<p style="margin:6px 0 0;font-size:14px">{text}</p>'


DEFAULTS: dict[str, dict[str, str]] = {
    "BIRTHDAY": {
        "subject": "🎂 Birthday reminder ({count})",
        "body_html": _heads_up(
            "🎂",
            "Birthdays to celebrate",
            "{count} colleague(s) have a birthday coming up.",
            _line("🎉 Turns {age} {when} · {event_date}"),
            "Take a moment to send your wishes.",
        ),
        "employee_subject": "Happy birthday, {first_name}! 🎂",
        "employee_body_html": _greeting(
            "🎂",
            "Happy Birthday, {first_name}!",
            "Everyone at {company_name} wishes you a wonderful day and a great year ahead.",
        ),
    },
    "WORK_ANNIVERSARY": {
        "subject": "🎉 Work anniversary reminder ({count})",
        "body_html": _heads_up(
            "🎉",
            "Work anniversaries",
            "{count} colleague(s) complete another year with us.",
            _line("🏅 {years} years with us {when} · {event_date}"),
            "Say thank you for the years they have given us.",
        ),
        "employee_subject": "Happy work anniversary, {first_name}! 🎉",
        "employee_body_html": _greeting(
            "🏅",
            "Congratulations, {first_name}!",
            "Today marks {years} years with {company_name}. Thank you for everything you do.",
        ),
    },
    "NEW_JOINER": {
        "subject": "👋 New joiners ({count})",
        "body_html": _heads_up(
            "👋",
            "New joiners",
            "{count} colleague(s) are about to join us.",
            _line("📅 Joins {when} · {joining_date}")
            + '<p style="margin:2px 0 0;font-size:13px;color:#6b7280">{manager_line}</p>',
            "Please have their desk, laptop and accounts ready.",
        ),
        "employee_subject": "Welcome to {company_name}, {first_name}! 👋",
        "employee_body_html": _greeting(
            "👋",
            "Welcome, {first_name}!",
            "We are delighted to have you at {company_name}. Wishing you a great start.",
        ),
    },
    "EXIT": {
        "subject": "Upcoming exits ({count})",
        "body_html": _heads_up(
            "📋",
            "Upcoming exits",
            "{count} colleague(s) are leaving.",
            _line("📅 Last working day {last_day} · {when}")
            + '<p style="margin:2px 0 0;font-size:13px;color:#6b7280">{manager_line}</p>',
            "Please complete handover, asset return and settlement on time.",
        ),
        "employee_subject": "Thank you, {first_name}",
        "employee_body_html": _greeting(
            "🙏",
            "Thank you, {first_name}",
            "Thank you for everything you did at {company_name}. We wish you all the best for "
            "what comes next.",
        ),
    },
}
