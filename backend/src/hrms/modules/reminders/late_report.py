"""
The late-arrivals report: a PDF that goes with the daily late-arrivals mail.

It opens with the day's totals, then shows the late people by department and by role, and lists
every person under their department. The people come from the outbox payload, so the report
always matches the mail it travels with. Rendering uses the same sandboxed WeasyPrint set-up
as the payslip: HTML built from escaped data, no outside URLs, the bundled fonts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from jinja2 import Environment, StrictUndefined

from hrms.modules.payroll.payslip.render import FONTS_DIR, bundled_only_fetcher
from hrms.modules.reminders.service import late_text

NONE_LABEL = "No department"
NO_ROLE = "No role"

_env = Environment(autoescape=True, undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
_env.filters["late"] = late_text

TEMPLATE = _env.from_string("""
<!doctype html>
<html><head><meta charset="utf-8"><style>
@font-face { font-family: Noto; src: url("NotoSans-Regular.ttf"); }
@font-face { font-family: Noto; font-weight: bold; src: url("NotoSans-Bold.ttf"); }
@page { size: A4; margin: 16mm 14mm 18mm;
  @bottom-left { content: "{{ company }} · Late arrivals · {{ day_text }}";
                 font: 8pt Noto; color: #6b7280; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages);
                  font: 8pt Noto; color: #6b7280; } }
* { box-sizing: border-box; }
body { font: 9.5pt/1.45 Noto, sans-serif; color: #111827; margin: 0; }
.band { background: {{ color }}; color: {{ on_color }}; padding: 14pt 16pt; border-radius: 6pt; }
.band .co { font-size: 9pt; opacity: .85; letter-spacing: .04em; text-transform: uppercase; }
.band h1 { font-size: 20pt; margin: 3pt 0 0; }
.band .sub { font-size: 10pt; opacity: .9; margin-top: 2pt; }
.tiles { display: flex; gap: 8pt; margin: 12pt 0 4pt; }
.tile { flex: 1; border: 1px solid #e5e7eb; border-radius: 6pt; padding: 9pt 10pt; }
.tile .n { font-size: 17pt; font-weight: bold; color: {{ color }}; }
.tile .l { font-size: 8pt; color: #6b7280; text-transform: uppercase; letter-spacing: .04em; }
h2 { font-size: 12pt; margin: 16pt 0 6pt; padding-bottom: 3pt; border-bottom: 2px solid {{ color }};
     break-after: avoid; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-size: 8pt; color: #6b7280; text-transform: uppercase;
     letter-spacing: .04em; padding: 5pt 6pt; background: #f3f4f6; }
td { padding: 5pt 6pt; border-bottom: 1px solid #eef0f3; vertical-align: middle; }
tr { break-inside: avoid; }
.who { table-layout: fixed; }
.r { text-align: right; } .c { text-align: center; }
.bar { background: #eef0f3; border-radius: 3pt; height: 6pt; width: 100%; }
.bar i { display: block; height: 6pt; border-radius: 3pt; background: {{ color }}; }
.pill { display: inline-block; padding: 1pt 7pt; border-radius: 10pt; font-size: 8pt;
        font-weight: bold; }
.sev0 { background: #fef3c7; color: #92400e; }
.sev1 { background: #ffedd5; color: #9a3412; }
.sev2 { background: #fee2e2; color: #991b1b; }
.dept { margin-top: 12pt; break-inside: avoid-page; }
.dept-head { display: flex; justify-content: space-between; align-items: baseline;
             background: #f9fafb; border-left: 3pt solid {{ color }}; padding: 6pt 8pt;
             break-after: avoid; }
.dept-head b { font-size: 10.5pt; } .muted { color: #6b7280; font-size: 8.5pt; }
.note { margin-top: 14pt; font-size: 8pt; color: #6b7280; }
</style></head><body>
<div class="band">
  <div class="co">{{ company }}</div>
  <h1>Late arrivals report</h1>
  <div class="sub">{{ day_text }}</div>
</div>

<div class="tiles">
  <div class="tile"><div class="n">{{ total }}</div><div class="l">People late</div></div>
  <div class="tile"><div class="n">{{ average | late }}</div>
    <div class="l">Average delay</div></div>
  <div class="tile"><div class="n">{{ longest | late }}</div>
    <div class="l">Longest delay</div></div>
  <div class="tile"><div class="n">{{ departments | length }}</div>
    <div class="l">Departments</div></div>
</div>

<h2>By department</h2>
<table>
  <tr><th>Department</th><th class="c">Late</th><th class="r">Average</th><th class="r">Longest</th>
      <th style="width:28%">Share of late people</th></tr>
  {% for d in departments %}
  <tr><td><b>{{ d.name }}</b></td><td class="c">{{ d.count }}</td>
      <td class="r">{{ d.average | late }}</td><td class="r">{{ d.longest | late }}</td>
      <td><div class="bar"><i style="width: {{ d.share }}%"></i></div></td></tr>
  {% endfor %}
</table>

<h2>By role</h2>
<table>
  <tr><th>Role</th><th class="c">Late</th><th class="r">Average</th><th class="r">Longest</th>
      <th>Departments</th></tr>
  {% for r in roles %}
  <tr><td><b>{{ r.name }}</b></td><td class="c">{{ r.count }}</td>
      <td class="r">{{ r.average | late }}</td><td class="r">{{ r.longest | late }}</td>
      <td class="muted">{{ r.departments }}</td></tr>
  {% endfor %}
</table>

<h2>Who was late</h2>
{% for d in departments %}
<div class="dept">
  <div class="dept-head"><b>{{ d.name }}</b>
    <span class="muted">{{ d.count }} late · average {{ d.average | late }}</span></div>
  <table class="who">
    <tr><th style="width:27%">Name</th><th style="width:20%">Role</th>
        <th style="width:21%">Manager</th><th class="r" style="width:11%">Expected</th>
        <th class="r" style="width:10%">Arrived</th>
        <th class="r" style="width:11%">Late by</th></tr>
    {% for p in d.people %}
    <tr><td><b>{{ p.full_name }}</b></td><td>{{ p.designation or "—" }}</td>
        <td>{{ p.manager_name or "—" }}</td>
        <td class="r">{{ p.expected_at }}</td><td class="r">{{ p.arrived_at }}</td>
        <td class="r"><span class="pill sev{{ p.severity }}">
          {{ p.late_minutes | late }}</span></td></tr>
    {% endfor %}
  </table>
</div>
{% endfor %}

<div class="note">Late is measured by the company's attendance policy, grace period included.
Times are in the company's timezone.</div>
</body></html>
""")


def _stats(people: list[dict]) -> dict:
    minutes = [p["late_minutes"] for p in people]
    return {
        "count": len(people),
        "average": round(sum(minutes) / len(minutes)),
        "longest": max(minutes),
    }


def build_view(people: list[dict]) -> dict:
    """Totals and the department and role groupings, biggest first."""
    by_dept: dict[str, list[dict]] = defaultdict(list)
    by_role: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        # A shade for how late: under half an hour, under an hour, an hour or more.
        shaded = {
            **p,
            "severity": 0 if p["late_minutes"] < 30 else 1 if p["late_minutes"] < 60 else 2,
        }
        by_dept[p["department"] or NONE_LABEL].append(shaded)
        by_role[p["designation"] or NO_ROLE].append(shaded)
    total = len(people)
    departments = [
        {
            "name": name,
            **_stats(rows),
            "share": round(100 * len(rows) / total),
            "people": sorted(rows, key=lambda r: (-r["late_minutes"], r["full_name"])),
        }
        for name, rows in by_dept.items()
    ]
    roles = [
        {
            "name": name,
            **_stats(rows),
            "departments": ", ".join(sorted({r["department"] or NONE_LABEL for r in rows})),
        }
        for name, rows in by_role.items()
    ]
    key = lambda g: (-g["count"], -g["average"], g["name"])  # noqa: E731
    return {
        "total": total,
        **{k: v for k, v in _stats(people).items() if k != "count"},
        "departments": sorted(departments, key=key),
        "roles": sorted(roles, key=key),
    }


def render_pdf(
    people: list[dict], company: str, day: date, color: str = "#2563eb", on_color: str = "#ffffff"
) -> bytes:
    """The report as PDF bytes. Blocking (a fraction of a second): run it in a thread."""
    from weasyprint import HTML

    html = TEMPLATE.render(
        company=company,
        color=color,
        on_color=on_color,
        day_text=f"{day:%A, %d %B %Y}",
        **build_view(people),
    )
    return HTML(
        string=html, base_url=FONTS_DIR.as_uri() + "/", url_fetcher=bundled_only_fetcher()
    ).write_pdf()


def filename(day: date) -> str:
    return f"late-arrivals-{day.isoformat()}.pdf"
