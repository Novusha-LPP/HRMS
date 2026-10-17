"""Export regression checks without any database or workbook-writing dependency."""

from copy import deepcopy
from datetime import UTC, date, datetime
from io import BytesIO
from posixpath import dirname, normpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from hrms.modules.reports.attendance_xlsx import CHART_NS, NS, PACKAGE_REL_NS, attendance_workbook

X = {"m": NS}


@pytest.fixture
def report():
    metrics = {
        "total_working_days": 29.5,
        "present_days": 22.5,
        "absent_days": 0.5,
        "half_day_pl": 1,
        "full_day_pl": 1,
        "total_pl_taken": 1.5,
        "lwp_taken": 0,
        "other_leave_days": 0,
        "week_off_days": 5,
        "holiday_days": 1,
        "opening_balance": None,
        "pl_taken": 0,
        "available_balance": 0,
        "total_work_minutes": 900,
        "average_hours_per_day": 7.5,
    }
    day = {
        "work_date": date(2026, 9, 1),
        "day_name": "Tue",
        "shift_start": "22:00",
        "shift_end": "07:00",
        "shift_name": "Night shift",
        "timezone": "Asia/Kolkata",
        "status": "HALF_DAY",
        "display_status": "Half Day (PL)",
        "paid_leave_days": 0.5,
        "lwp_days": 0,
        "first_punch_in": datetime(2026, 9, 1, 16, 30, tzinfo=UTC),
        "last_punch_out": datetime(2026, 9, 2, 1, 30, tzinfo=UTC),
        "effective_minutes": 480,
        "late_by_minutes": 5,
        "early_departure_minutes": 10,
        "department": "Operations",
        "holiday_name": None,
        "leave_type": "Privilege Leave",
    }
    employee = {
        **metrics,
        "employment_id": "emp_one",
        "employee_number": "0007",
        "name": '=HYPERLINK("https://example.invalid") & <literal>\x01',
        "legal_entity_id": "le_one",
        "company": "Company / A",
        "department": "Operations",
        "days": [day],
    }
    return {
        "from_date": date(2026, 9, 1),
        "to_date": date(2026, 9, 30),
        "generated_at": datetime(2026, 10, 16, tzinfo=UTC),
        "employees": [employee],
        "companies": [{**metrics, "employee_count": 1, "company": employee["company"]}],
        "totals": {**metrics, "employee_count": 1},
        "notes": ["PL means privilege leave."],
    }


def _xml(archive, name):
    return ET.fromstring(archive.read(name))


def _value(sheet, address):
    cell = sheet.find(f'.//m:c[@r="{address}"]', X)
    assert cell is not None
    if cell.get("t") == "inlineStr":
        return cell.find("m:is/m:t", X).text
    value = cell.find("m:v", X)
    return None if value is None else float(value.text)


def test_export_keeps_fractional_counts_literal_identifiers_and_missing_balances(report):
    before = deepcopy(report)
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        sheet = _xml(archive, "xl/worksheets/sheet3.xml")
        assert _value(sheet, "A6") == '=HYPERLINK("https://example.invalid") & <literal>'
        assert _value(sheet, "B6") == "0007"
        assert _value(sheet, "D6") == 29.5
        assert _value(sheet, "E6") == 22.5
        assert _value(sheet, "N6") is None  # missing opening balance
        assert _value(sheet, "O6") == 0  # an actual zero ledger debit
        assert _value(sheet, "P6") == 0  # an actual zero available balance
        assert _value(sheet, "Q6") == 7.5 / 24
        assert sheet.findall(".//m:f", X) == []
        assert sheet.find("m:autoFilter", X).get("ref") == "A5:Q6"
        pane = sheet.find("m:sheetViews/m:sheetView/m:pane", X)
        assert (pane.get("xSplit"), pane.get("ySplit")) == ("1", "5")
    assert report == before


def test_export_uses_local_clock_overnight_dates_and_numeric_durations(report):
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        sheet = _xml(archive, "xl/worksheets/sheet3.xml")
        assert _value(sheet, "A10") == (date(2026, 9, 1) - date(1899, 12, 30)).days
        assert _value(sheet, "C10") == "Night shift 22:00–07:00"
        assert _value(sheet, "D10") == "Half Day (PL)"
        assert _value(sheet, "F10") > _value(sheet, "E10")
        assert _value(sheet, "E10") % 1 == pytest.approx(22 / 24)
        assert _value(sheet, "F10") % 1 == pytest.approx(7 / 24)
        assert _value(sheet, "G10") == 480 / 1440
        assert _value(sheet, "G11") == 900 / 1440
        assert _value(sheet, "H10") == "Late In (5m); Early Out (10m)"
        assert _value(sheet, "I10") == "Asia/Kolkata"
        assert _value(sheet, "L10") == "Privilege Leave"


def test_export_deduplicates_truncated_sheet_names_and_keeps_every_employee(report):
    first, second = deepcopy(report["employees"][0]), deepcopy(report["employees"][0])
    first.update(company="A" * 31 + " first", legal_entity_id="le_first")
    second.update(company="A" * 31 + " second", legal_entity_id="le_second")
    report["employees"] = [first, second]
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        workbook = _xml(archive, "xl/workbook.xml")
        names = [sheet.get("name") for sheet in workbook.find("m:sheets", X)]
        assert names == ["Overview", "Employee Summary", "A" * 31, "A" * 27 + " (2)"]
        for number in (3, 4):
            sheet = _xml(archive, f"xl/worksheets/sheet{number}.xml")
            assert _value(sheet, "B6") == "0007"
            assert _value(sheet, "A11") == "Total Worked Hours"


def test_empty_export_is_valid_and_retains_period_and_notes(report):
    report["employees"], report["companies"] = [], []
    report["totals"]["employee_count"] = 0
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        workbook = _xml(archive, "xl/workbook.xml")
        assert len(workbook.find("m:sheets", X)) == 2
        sheet = _xml(archive, "xl/worksheets/sheet1.xml")
        for row in (4, 5):
            assert sheet.find(f'.//m:row[@r="{row}"]/m:c', X) is None
        assert _value(sheet, "B26") == 0
        assert "2026-09-01 to 2026-09-30" in _value(sheet, "A2")
        assert _value(sheet, "A29") == "PL means privilege leave."


def test_employee_summary_has_filters_and_preserves_source_values(report):
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        sheet = _xml(archive, "xl/worksheets/sheet2.xml")
        assert _value(sheet, "A6") == "Company / A"
        assert _value(sheet, "C6") == "0007"
        assert _value(sheet, "F6") == 22.5
        assert _value(sheet, "O6") is None
        assert _value(sheet, "P6") == 0
        assert _value(sheet, "R6") == 7.5 / 24
        assert sheet.find("m:sheetViews/m:sheetView/m:pane", X).get("topLeftCell") == "C6"
        table = _xml(archive, "xl/tables/table1.xml")
        assert table.get("ref") == "A5:R6"
        assert table.find("m:autoFilter", X).get("ref") == "A5:R6"
        assert len(table.find("m:tableColumns", X)) == 18


def test_headcount_chart_references_company_summary_and_has_cached_points(report):
    report["companies"].append(
        {**report["companies"][0], "company": "Larger & Co", "employee_count": 4}
    )
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        c = {"c": CHART_NS}
        first = _xml(archive, "xl/charts/chart1.xml")
        assert [name for name in archive.namelist() if name.startswith("xl/charts/")] == [
            "xl/charts/chart1.xml"
        ]
        assert first.find(".//c:barDir", c).get("val") == "bar"
        assert first.find(".//c:strCache/c:pt/c:v", c).text == "Larger & Co"
        assert [point.find("c:v", c).text for point in first.findall(".//c:numCache/c:pt", c)] == [
            "4",
            "1",
        ]
        assert first.find(".//c:cat/c:strRef/c:f", c).text == "'Overview'!$A$26:$A$27"
        assert first.find(".//c:val/c:numRef/c:f", c).text == "'Overview'!$B$26:$B$27"
        for cache in first.findall(".//c:numCache", c) + first.findall(".//c:strCache", c):
            assert cache.find("c:ptCount", c).get("val") == "2"
            assert len(cache.findall("c:pt", c)) == 2
        drawing = _xml(archive, "xl/drawings/drawing1.xml")
        assert len(drawing) == 1
        assert len(_xml(archive, "xl/drawings/_rels/drawing1.xml.rels")) == 1
        assert b"chart2.xml" not in archive.read("[Content_Types].xml")
        for rel_name in archive.namelist():
            if not rel_name.endswith(".rels"):
                continue
            parent = "" if rel_name == "_rels/.rels" else dirname(dirname(rel_name))
            for relationship in _xml(archive, rel_name).findall(
                f"{{{PACKAGE_REL_NS}}}Relationship"
            ):
                target = normpath(parent + "/" + relationship.get("Target")).lstrip("/")
                assert target in archive.namelist(), (rel_name, target)


def test_large_company_chart_is_labeled_and_full_data_remains_available(report):
    template = report["companies"][0]
    report["companies"] = [
        {**template, "company": f"Company {index}", "employee_count": index + 1}
        for index in range(12)
    ]
    with ZipFile(BytesIO(attendance_workbook(report))) as archive:
        chart = _xml(archive, "xl/charts/chart1.xml")
        c = {"c": CHART_NS}
        assert chart.find(".//c:strCache/c:ptCount", c).get("val") == "10"
        text = " ".join(chart.itertext())
        assert "10 largest companies" in text
        overview = _xml(archive, "xl/worksheets/sheet1.xml")
        assert _value(overview, "A26") == "Company 11"
        assert _value(overview, "A37") == "Company 0"
