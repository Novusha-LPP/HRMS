"""A dependency-free Excel export of the read-only attendance and leave report."""

from collections.abc import Mapping
from datetime import date, datetime
from io import BytesIO
from math import isfinite
from re import sub
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
ART_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
for _prefix, _namespace in (("c", CHART_NS), ("xdr", DRAWING_NS), ("a", ART_NS), ("r", REL_NS)):
    ET.register_namespace(_prefix, _namespace)

# The reference has two different PL quantities: attendance and leave-ledger debits.
METRICS = [
    ("total_working_days", "Total Working Days"),
    ("present_days", "Present"),
    ("absent_days", "Absent"),
    ("half_day_pl", "Half Day PL"),
    ("full_day_pl", "Full Day PL"),
    ("total_pl_taken", "Total PL Taken"),
    ("lwp_taken", "LWP Taken"),
    ("other_leave_days", "Other Leave"),
    ("week_off_days", "Week Off"),
    ("holiday_days", "Holiday"),
    ("opening_balance", "Opening PL Balance"),
    ("pl_taken", "PL Taken (Ledger)"),
    ("available_balance", "Available Balance"),
    ("average_hours_per_day", "Avg Hours/Day"),
]


def _plain_text(value: Any) -> str:
    # XML 1.0 disallows several control characters even in an escaped string.
    return sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", str(value))[:32767]


def _xml_text(value: Any) -> str:
    return escape(_plain_text(value))


def _column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(row: int, col: int, value: Any, style: int = 0) -> str:
    address = f"{_column(col)}{row}"
    if value is None or value == "":
        return f'<c r="{address}" s="{style}"/>'
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return f'<c r="{address}" s="{style}"><v>{value}</v></c>'
    # inlineStr keeps names beginning with =, +, -, or @ as literal text.
    return (
        f'<c r="{address}" s="{style}" t="inlineStr"><is>'
        f'<t xml:space="preserve">{_xml_text(value)}</t></is></c>'
    )


def _date_serial(value: date | str) -> int:
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return (parsed - date(1899, 12, 30)).days


def _timestamp_serial(value: datetime | str | None, timezone: str) -> float | None:
    if not value:
        return None
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    local = parsed.astimezone(ZoneInfo(timezone)) if parsed.tzinfo else parsed
    return (
        _date_serial(local.date()) + (local.hour * 3600 + local.minute * 60 + local.second) / 86400
    )


def _metric_values(item: Mapping[str, Any]) -> list[Any]:
    values = [item.get(key) for key, _ in METRICS]
    # Excel time is a fraction of a day. Keep duration cells numeric and summable.
    if values[-1] is not None:
        values[-1] /= 24
    return values


def _metric_styles(total: bool = False) -> list[int]:
    counts = {"half_day_pl", "full_day_pl", "week_off_days", "holiday_days"}
    return [
        (10 if total else 7)
        if key == "average_hours_per_day"
        else (14 if total else 13)
        if key in counts
        else (9 if total else 4)
        for key, _ in METRICS
    ]


class _Sheet:
    def __init__(self, title: str, widths: list[int], freeze: int = 5, freeze_columns: int = 1):
        self.title = title
        self.widths = widths
        self.freeze = freeze
        self.freeze_columns = freeze_columns
        self.rows: list[str] = []
        self.merges: list[str] = []
        self.autofilter: str | None = None
        self.drawing = False
        self.table = False

    def row(self, values: list[Any], styles: int | list[int] = 0, height: int = 23) -> int:
        index = len(self.rows) + 1
        style_list = [styles] * len(values) if isinstance(styles, int) else styles
        self.rows.append(
            f'<row r="{index}" ht="{height}" customHeight="1">'
            + "".join(
                _cell(index, col, value, style_list[col - 1]) for col, value in enumerate(values, 1)
            )
            + "</row>"
        )
        return index

    def merged(self, text: Any, style: int, end: int | None = None, height: int = 28) -> None:
        row = self.row([text], style, height)
        self.merges.append(f"A{row}:{_column(end or len(self.widths))}{row}")

    def xml(self) -> str:
        last = max(len(self.rows), 1)
        cols = "".join(
            f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(self.widths, 1)
        )
        merges = (
            (
                f'<mergeCells count="{len(self.merges)}">'
                + "".join(f'<mergeCell ref="{m}"/>' for m in self.merges)
                + "</mergeCells>"
            )
            if self.merges
            else ""
        )
        auto = f'<autoFilter ref="{self.autofilter}"/>' if self.autofilter else ""
        pane = (
            (
                '<sheetViews><sheetView workbookViewId="0" showGridLines="0">'
                f'<pane xSplit="{self.freeze_columns}" ySplit="{self.freeze}" '
                f'topLeftCell="{_column(self.freeze_columns + 1)}{self.freeze + 1}" '
                'activePane="bottomRight" state="frozen"/>'
                "</sheetView></sheetViews>"
            )
            if self.freeze
            else ('<sheetViews><sheetView workbookViewId="0" showGridLines="0"/></sheetViews>')
        )
        drawings = '<drawing r:id="rId1"/>' if self.drawing else ""
        tables = '<tableParts count="1"><tablePart r:id="rId1"/></tableParts>' if self.table else ""
        return (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{NS}" xmlns:r="{REL_NS}">'
            f'<dimension ref="A1:{_column(len(self.widths))}{last}"/>'
            f'{pane}<sheetFormatPr defaultRowHeight="23"/>'
            f"<cols>{cols}</cols><sheetData>{''.join(self.rows)}</sheetData>{auto}{merges}"
            '<printOptions horizontalCentered="1"/>'
            '<pageMargins left="0.25" right="0.25" top="0.4" bottom="0.4" '
            'header="0.15" footer="0.15"/>'
            '<pageSetup paperSize="8" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
            f"{drawings}{tables}"
            "</worksheet>"
        )


STYLES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS}">
  <numFmts count="4">
    <numFmt numFmtId="164" formatCode="#,##0.0"/>
    <numFmt numFmtId="165" formatCode="dd mmm yyyy"/>
    <numFmt numFmtId="166" formatCode="h:mm AM/PM"/>
    <numFmt numFmtId="167" formatCode="[h]&quot;h &quot;mm&quot;m&quot;"/>
  </numFmts>
  <fonts count="5">
    <font><sz val="11"/><color rgb="FF243449"/><name val="Calibri"/></font>
    <font><b/><sz val="20"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><sz val="10"/><color rgb="FF526579"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FF123F49"/><name val="Calibri"/></font>
  </fonts>
  <fills count="5">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid">
      <fgColor rgb="FF123F49"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid">
      <fgColor rgb="FFEDF5F5"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid">
      <fgColor rgb="FFF5F8FB"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2"><border/><border><bottom style="hair">
    <color rgb="FFDDE5ED"/></bottom></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="15">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0">
      <alignment vertical="center" horizontal="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0">
      <alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center"/></xf>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center"/></xf>
    <xf numFmtId="167" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
    <xf numFmtId="0" fontId="4" fillId="3" borderId="0" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="164" fontId="4" fillId="3" borderId="0" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
    <xf numFmtId="167" fontId="4" fillId="3" borderId="0" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="3" fontId="0" fillId="0" borderId="1" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
    <xf numFmtId="3" fontId="4" fillId="3" borderId="0" xfId="0">
      <alignment vertical="center" horizontal="right"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _sheet_name(name: str, used: set[str]) -> str:
    base = sub(r"[\[\]:*?/\\\x00-\x1f]", " ", name).strip().strip("'") or "Company"
    candidate, suffix = base[:31].strip("'"), 1
    while candidate.casefold() in used:
        suffix += 1
        tail = f" ({suffix})"
        candidate = base[: 31 - len(tail)] + tail
    used.add(candidate.casefold())
    return candidate


def _daily_status(day: Mapping[str, Any]) -> str:
    if day.get("display_status"):
        return day["display_status"]
    status = day["status"]
    pl, lwp = day.get("paid_leave_days", 0), day.get("lwp_days", 0)
    if 0 < pl < 1:
        return "Half Day (PL)"
    if 0 < lwp < 1:
        return "Half Day (LWP)"
    if pl >= 1:
        return "PL"
    if lwp >= 1:
        return "LWP"
    return {
        "WEEKEND": "Weekly Off",
        "ON_LEAVE": "On Leave",
        "HALF_DAY": "Half Day",
        "EARLY_DEPARTURE": "Early Departure",
    }.get(status, status.replace("_", " ").title())


def _element(parent, namespace: str, tag_name: str, text: Any = None, **attributes):
    element = ET.SubElement(parent, f"{{{namespace}}}{tag_name}", attributes)
    if text is not None:
        element.text = _plain_text(text)
    return element


def _chart_xml(companies: list[Mapping[str, Any]], first_row: int) -> bytes:
    """The editable headcount chart references cells and includes offline caches."""
    chart_space = ET.Element(f"{{{CHART_NS}}}chartSpace")
    chart = _element(chart_space, CHART_NS, "chart")
    title = _element(chart, CHART_NS, "title")
    rich = _element(_element(title, CHART_NS, "tx"), CHART_NS, "rich")
    _element(rich, ART_NS, "bodyPr")
    _element(rich, ART_NS, "lstStyle")
    paragraph = _element(rich, ART_NS, "p")
    run = _element(paragraph, ART_NS, "r")
    _element(run, ART_NS, "rPr", lang="en-US", sz="1200")
    label = "Employees by company"
    if len(companies) > 10:
        label += " — 10 largest companies"
    _element(run, ART_NS, "t", label)
    _element(title, CHART_NS, "overlay", val="0")
    plot = _element(chart, CHART_NS, "plotArea")
    _element(plot, CHART_NS, "layout")
    bars = _element(plot, CHART_NS, "barChart")
    _element(bars, CHART_NS, "barDir", val="bar")
    _element(bars, CHART_NS, "grouping", val="clustered")
    visible = companies[:10]
    last_row = first_row + len(visible) - 1
    series = [("Employees", "employee_count", "B", "146C78")]
    for index, (name, field, column, color) in enumerate(series):
        item = _element(bars, CHART_NS, "ser")
        _element(item, CHART_NS, "idx", val=str(index))
        _element(item, CHART_NS, "order", val=str(index))
        _element(_element(item, CHART_NS, "tx"), CHART_NS, "v", name)
        fill = _element(_element(item, CHART_NS, "spPr"), ART_NS, "solidFill")
        _element(fill, ART_NS, "srgbClr", val=color)
        category = _element(_element(item, CHART_NS, "cat"), CHART_NS, "strRef")
        _element(category, CHART_NS, "f", f"'Overview'!$A${first_row}:$A${last_row}")
        labels = _element(category, CHART_NS, "strCache")
        _element(labels, CHART_NS, "ptCount", val=str(len(visible)))
        values = _element(_element(item, CHART_NS, "val"), CHART_NS, "numRef")
        _element(values, CHART_NS, "f", f"'Overview'!${column}${first_row}:${column}${last_row}")
        numbers = _element(values, CHART_NS, "numCache")
        _element(numbers, CHART_NS, "formatCode", "0")
        _element(numbers, CHART_NS, "ptCount", val=str(len(visible)))
        for point, company in enumerate(visible):
            _element(
                _element(labels, CHART_NS, "pt", idx=str(point)), CHART_NS, "v", company["company"]
            )
            if company.get(field) is not None:
                _element(
                    _element(numbers, CHART_NS, "pt", idx=str(point)), CHART_NS, "v", company[field]
                )
    _element(bars, CHART_NS, "gapWidth", val="80")
    _element(bars, CHART_NS, "overlap", val="0")
    category_axis, value_axis = "100", "101"
    _element(bars, CHART_NS, "axId", val=category_axis)
    _element(bars, CHART_NS, "axId", val=value_axis)
    for kind, axis_id, other, position in (
        ("catAx", category_axis, value_axis, "l"),
        ("valAx", value_axis, category_axis, "b"),
    ):
        axis = _element(plot, CHART_NS, kind)
        _element(axis, CHART_NS, "axId", val=axis_id)
        scaling = _element(axis, CHART_NS, "scaling")
        _element(scaling, CHART_NS, "orientation", val="maxMin" if kind == "catAx" else "minMax")
        if kind == "valAx":
            _element(scaling, CHART_NS, "min", val="0")
            largest = max(int(company["employee_count"]) for company in visible)
            step = max(1, (largest + 4) // 5)
            _element(scaling, CHART_NS, "max", val=str(((largest + step - 1) // step) * step))
        _element(axis, CHART_NS, "axPos", val=position)
        _element(axis, CHART_NS, "numFmt", formatCode="0", sourceLinked="0")
        _element(axis, CHART_NS, "tickLblPos", val="nextTo")
        _element(axis, CHART_NS, "crossAx", val=other)
        _element(axis, CHART_NS, "crosses", val="max" if kind == "valAx" else "autoZero")
        if kind == "valAx":
            _element(axis, CHART_NS, "majorUnit", val=str(step))
    _element(chart, CHART_NS, "plotVisOnly", val="1")
    _element(chart, CHART_NS, "dispBlanksAs", val="gap")
    return ET.tostring(chart_space, encoding="utf-8", xml_declaration=True)


def _drawing_xml() -> bytes:
    drawing = ET.Element(f"{{{DRAWING_NS}}}wsDr")
    anchor = _element(drawing, DRAWING_NS, "twoCellAnchor")
    for name, column, row in (("from", 0, 7), ("to", 8, 22)):
        corner = _element(anchor, DRAWING_NS, name)
        for field, value in (("col", column), ("colOff", 0), ("row", row), ("rowOff", 0)):
            _element(corner, DRAWING_NS, field, value)
    frame = _element(anchor, DRAWING_NS, "graphicFrame", macro="")
    props = _element(frame, DRAWING_NS, "nvGraphicFramePr")
    _element(props, DRAWING_NS, "cNvPr", id="1", name="Attendance chart 1")
    _element(props, DRAWING_NS, "cNvGraphicFramePr")
    transform = _element(frame, DRAWING_NS, "xfrm")
    _element(transform, ART_NS, "off", x="0", y="0")
    _element(transform, ART_NS, "ext", cx="0", cy="0")
    data = _element(_element(frame, ART_NS, "graphic"), ART_NS, "graphicData", uri=CHART_NS)
    _element(data, CHART_NS, "chart", **{f"{{{REL_NS}}}id": "rId1"})
    _element(anchor, DRAWING_NS, "clientData")
    return ET.tostring(drawing, encoding="utf-8", xml_declaration=True)


def _relationships(items: list[tuple[str, str]]) -> bytes:
    relationships = ET.Element("Relationships", xmlns=PACKAGE_REL_NS)
    for index, (kind, target) in enumerate(items, 1):
        ET.SubElement(
            relationships, "Relationship", Id=f"rId{index}", Type=f"{REL_NS}/{kind}", Target=target
        )
    return ET.tostring(relationships, encoding="utf-8", xml_declaration=True)


def _employee_table(headers: list[str], last_row: int) -> bytes:
    table = ET.Element(
        "table",
        xmlns=NS,
        id="1",
        name="AttendanceEmployees",
        displayName="AttendanceEmployees",
        ref=f"A5:R{last_row}",
        totalsRowShown="0",
    )
    ET.SubElement(table, "autoFilter", ref=f"A5:R{last_row}")
    columns = ET.SubElement(table, "tableColumns", count=str(len(headers)))
    for index, label in enumerate(headers, 1):
        ET.SubElement(columns, "tableColumn", id=str(index), name=label)
    ET.SubElement(
        table,
        "tableStyleInfo",
        name="TableStyleMedium2",
        showFirstColumn="0",
        showLastColumn="0",
        showRowStripes="1",
        showColumnStripes="0",
    )
    return ET.tostring(table, encoding="utf-8", xml_declaration=True)


def attendance_workbook(report: Mapping[str, Any]) -> bytes:
    """Export every employee and daily row; no source records or formulas are modified."""
    period = f"Period: {report['from_date']} to {report['to_date']}"
    overview = _Sheet("Overview", [42, 12] + [16] * (len(METRICS) - 1) + [19], freeze=0)
    overview.merged("Attendance & leave register", 1, height=40)
    overview.merged(f"{period}    Generated: {report['generated_at']}", 3, height=32)
    overview.row([])
    total = report["totals"]
    while len(overview.rows) < 23:
        overview.row([])
    overview.merged("Company summary", 8)
    overview.row(["Company", "Employees"] + [label for _, label in METRICS], 2, 44)
    companies = sorted(
        report["companies"], key=lambda item: (-item["employee_count"], item["company"])
    )
    for company in companies:
        overview.row(
            [company["company"], company["employee_count"]] + _metric_values(company),
            [12, 13] + _metric_styles(),
            height=32,
        )
    overview.row(
        ["Total", total["employee_count"]] + _metric_values(total),
        [8, 14] + _metric_styles(total=True),
    )
    if companies:
        overview.autofilter = f"A25:{_column(2 + len(METRICS))}{25 + len(companies)}"
        overview.drawing = True
    overview.row([])
    overview.merged("Definitions and availability", 8)
    for note in report.get("notes", []):
        overview.merged(note, 3, height=40)
    overview.merged(
        "Blank balance cells mean the PL ledger balance is unavailable "
        "for this period or your access scope.",
        3,
        height=32,
    )
    employee_summary = _Sheet(
        "Employee Summary", [42, 34, 19, 25] + [16] * (len(METRICS) - 1) + [19], freeze_columns=2
    )
    employee_summary.merged("Attendance & leave — employee summary", 1, height=40)
    employee_summary.merged(period, 3)
    employee_summary.row([])
    employee_summary.merged("Filter the headers to find a company or employee", 8)
    employee_headers = ["Company", "Employee", "Employee ID", "Department"] + [
        label for _, label in METRICS
    ]
    employee_summary.row(employee_headers, 2, 44)
    for employee in report["employees"]:
        employee_summary.row(
            [
                employee["company"],
                employee["name"],
                employee["employee_number"],
                employee.get("department"),
            ]
            + _metric_values(employee),
            [12, 12, 0, 12] + _metric_styles(),
            height=32,
        )
    employee_summary.table = bool(report["employees"])
    sheets = [overview, employee_summary]
    used = {"overview", "employee summary"}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for employee in report["employees"]:
        groups.setdefault(employee["legal_entity_id"], []).append(employee)
    for employees in groups.values():
        sheet = _Sheet(
            _sheet_name(employees[0]["company"], used),
            [34, 19, 25] + [16] * (len(METRICS) - 1) + [19],
        )
        sheet.merged(f"{employees[0]['company']} — Attendance & leave register", 1, height=40)
        sheet.merged(f"{period}    Staff count: {len(employees)}", 3)
        sheet.row([])
        sheet.merged("Employee summary", 8)
        sheet.row(
            ["Employee", "Employee ID", "Department"] + [label for _, label in METRICS], 2, 44
        )
        for employee in employees:
            sheet.row(
                [employee["name"], employee["employee_number"], employee.get("department")]
                + _metric_values(employee),
                [12, 0, 12] + _metric_styles(),
                height=32,
            )
        sheet.autofilter = f"A5:{_column(3 + len(METRICS))}{5 + len(employees)}"
        for employee in employees:
            sheet.row([])
            sheet.merged(f"Daily logs: {employee['name']} ({employee['employee_number']})", 8)
            sheet.row(
                [
                    "Date",
                    "Day",
                    "Shift",
                    "Status",
                    "In Time",
                    "Out Time",
                    "Total Hours",
                    "Late In / Early Out",
                    "Timezone",
                    "Department",
                    "Holiday",
                    "Leave Type",
                ],
                2,
                36,
            )
            for day in employee["days"]:
                timezone = day.get("timezone") or "UTC"
                shift = "–".join([day["shift_start"][:5], day["shift_end"][:5]])
                if day.get("shift_name"):
                    shift = f"{day['shift_name']} {shift}"
                late, early = day["late_by_minutes"], day["early_departure_minutes"]
                timing = "; ".join(
                    ([f"Late In ({late}m)"] if late else [])
                    + ([f"Early Out ({early}m)"] if early else [])
                )
                if not timing:
                    timing = "On Time" if day.get("first_punch_in") else "—"
                sheet.row(
                    [
                        _date_serial(day["work_date"]),
                        day["day_name"],
                        shift,
                        _daily_status(day),
                        _timestamp_serial(day.get("first_punch_in"), timezone),
                        _timestamp_serial(day.get("last_punch_out"), timezone),
                        day["effective_minutes"] / 1440
                        if day.get("first_punch_in") or day["effective_minutes"]
                        else None,
                        timing,
                        timezone,
                        day.get("department"),
                        day.get("holiday_name"),
                        day.get("leave_type"),
                    ],
                    [5, 0, 12, 12, 6, 6, 7, 12, 0, 12, 12, 12],
                    height=34,
                )
            sheet.row(
                [
                    "Total Worked Hours",
                    None,
                    None,
                    None,
                    None,
                    None,
                    employee["total_work_minutes"] / 1440,
                ],
                [8] * 6 + [10],
            )
        sheets.append(sheet)

    output = BytesIO()
    extra_types = ""
    if companies:
        extra_types += (
            '<Override PartName="/xl/drawings/drawing1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
            '<Override PartName="/xl/charts/chart1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
        )
    if report["employees"]:
        extra_types += (
            '<Override PartName="/xl/tables/table1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
        )
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + extra_types
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<workbook xmlns="{NS}" xmlns:r="{REL_NS}"><sheets>'
            + "".join(
                f'<sheet name={quoteattr(sheet.title)} sheetId="{i}" r:id="rId{i}"/>'
                for i, sheet in enumerate(sheets, 1)
            )
            + "</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Type="{REL_NS}/worksheet" '
                f'Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, len(sheets) + 1)
            )
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{REL_NS}/styles" '
            'Target="styles.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/styles.xml", STYLES)
        for index, sheet in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet.xml())
        if companies:
            archive.writestr(
                "xl/worksheets/_rels/sheet1.xml.rels",
                _relationships(
                    [
                        ("drawing", "../drawings/drawing1.xml"),
                    ]
                ),
            )
            archive.writestr("xl/drawings/drawing1.xml", _drawing_xml())
            archive.writestr(
                "xl/drawings/_rels/drawing1.xml.rels",
                _relationships(
                    [
                        ("chart", "../charts/chart1.xml"),
                    ]
                ),
            )
            archive.writestr("xl/charts/chart1.xml", _chart_xml(companies, 26))
        if report["employees"]:
            archive.writestr(
                "xl/worksheets/_rels/sheet2.xml.rels",
                _relationships(
                    [
                        ("table", "../tables/table1.xml"),
                    ]
                ),
            )
            archive.writestr(
                "xl/tables/table1.xml",
                _employee_table(
                    employee_headers,
                    5 + len(report["employees"]),
                ),
            )
    return output.getvalue()
