"""
The payslip document without a database: Indian amounts and words, masking, what the view
keeps and hides, colour contrast, image uploads, and a renderer that can't reach outside.
"""

import io
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from PIL import Image

from hrms.modules.branding import images, resolve
from hrms.modules.branding.models import AssetKind
from hrms.modules.payroll.payslip import document, render, sample
from hrms.modules.payroll.payslip.formatting import amount_in_words, format_inr, mask

D = Decimal


@pytest.mark.parametrize(
    ("amount", "printed", "words"),
    [
        ("41362.91", "41,362.91", "Rupees Forty-One Thousand Three Hundred Sixty-Two and "
         "Ninety-One Paise Only"),
        ("0", "0.00", "Rupees Zero Only"),
        ("1100000", "11,00,000.00", "Rupees Eleven Lakh Only"),
        ("10000000", "1,00,00,000.00", "Rupees One Crore Only"),
        ("123456789.05", "12,34,56,789.05", "Rupees Twelve Crore Thirty-Four Lakh Fifty-Six "
         "Thousand Seven Hundred Eighty-Nine and Five Paise Only"),
        ("999.995", "1,000.00", "Rupees One Thousand Only"),  # rounds half up to paise
        ("-5.5", "-5.50", "Minus Rupees Five and Fifty Paise Only"),
    ],
)  # fmt: skip
def test_amounts_print_the_indian_way(amount, printed, words):
    assert format_inr(D(amount)) == printed
    assert amount_in_words(D(amount)) == words


def test_identifiers_keep_only_the_last_four_characters():
    assert mask("50100123454821") == "XXXXXXXXXX4821"
    assert mask("ABCDE1234F") == "XXXXXX234F"
    assert mask("12") == "12"
    assert mask(None) is None


def _data():
    return sample.sample_payslip(date(2026, 10, 29), datetime(2026, 10, 29, 18, 20), "ACME")


def test_the_sample_adds_up():
    data = _data()
    assert data.period_label == "September 2026"
    assert (data.days_in_period, data.paid_days, data.lop_days) == (D(30), D(29), D(1))
    view = document.build_view(data, document.Issuer(name="Acme"), document.TemplateSettings())
    assert view.totals["gross"] == "44,563.34"
    assert view.totals["deductions"] == "3,250.00"
    assert view.net_pay == "41,313.34"
    assert view.net_pay_words.startswith("Rupees Forty-One Thousand Three Hundred Thirteen")


def test_view_follows_the_template_settings():
    data = _data()
    issuer = document.Issuer(name="Acme", signer=document.Signer("Priya Nair", "HR"))
    plain = document.build_view(data, issuer, document.TemplateSettings())
    assert "ESIC" not in [ln.label for ln in plain.deductions]  # zero lines are hidden
    assert plain.employer_contributions == ()
    assert plain.signature_mode == "COMPUTER_GENERATED" and plain.issuer.signer is None
    assert [label for label, _ in plain.employee_fields][:2] == ["Employee number", "Designation"]

    settings = document.TemplateSettings(
        hide_zero_lines=False,
        show_employer_contributions=True,
        show_leave_balances=True,
        signature_mode="SIGNATORY",
        employee_fields=("pan", "bank_account"),
    )
    full = document.build_view(data, issuer, settings)
    assert "ESIC" in [ln.label for ln in full.deductions]
    assert full.employer_contributions and full.show_leave_balances
    assert full.issuer.signer and full.issuer.signer.name == "Priya Nair"
    assert full.employee_fields == (
        ("PAN", "XXXXXX234F"),
        ("Bank account", "HDFC Bank XXXXXXXXXX4821"),
    )

    compact = document.build_view(data, issuer, replace(settings, layout="COMPACT"))
    assert not compact.show_attendance and not compact.show_leave_balances  # half a page


def test_brand_colours_stay_readable():
    assert resolve.readable_on_white("#0F766E") == "#0F766E"
    yellow = resolve.readable_on_white("#FACC15")
    assert yellow != "#FACC15" and resolve.contrast(yellow, resolve.WHITE) >= 4.5
    assert resolve.text_on("#FACC15") == resolve.INK  # dark text on a light band
    assert resolve.text_on("#0F766E") == resolve.WHITE
    view = document.build_view(
        _data(), document.Issuer(name="Acme", primary_color="#facc15"), document.TemplateSettings()
    )
    assert view.colors["on_primary"] == resolve.INK and view.colors["primary_text"] == yellow


def test_company_text_is_escaped_not_rendered():
    issuer = document.Issuer(name='<img src="http://evil.example/x">Acme', footer_text="<b>x</b>")
    html = render.render_html(document.build_view(_data(), issuer, document.TemplateSettings()))
    assert "evil.example" in html and '<img src="http://evil' not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_the_renderer_reads_only_embedded_data_and_its_fonts():
    fetcher = render.bundled_only_fetcher()
    with pytest.raises(ValueError):
        fetcher.fetch("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ValueError):
        fetcher.fetch("file:///etc/passwd")
    with pytest.raises(ValueError):
        fetcher.fetch((render.FONTS_DIR / ".." / ".." / "__init__.py").as_uri())
    font = fetcher.fetch((render.FONTS_DIR / "NotoSans-Regular.ttf").as_uri())
    assert font is not None


@pytest.mark.parametrize("layout", document.LAYOUTS)
def test_every_layout_renders_a_one_page_pdf(layout):
    settings = document.TemplateSettings(layout=layout, signature_mode="SIGNATORY")
    issuer = document.Issuer(
        name="Acme Logistics Pvt Ltd",
        address="Plot 12, Mumbai",
        logo_png=_png(400, 120),
        signer=document.Signer("Priya Nair", "Head of HR", _png(300, 90)),
    )
    view = document.build_view(_data(), issuer, settings, sample=True)
    assert render.render_pdf(view).startswith(b"%PDF-")
    assert render.page_count(view) == 1
    png = Image.open(io.BytesIO(render.render_png(view)))
    assert png.width == render.PREVIEW_WIDTH and png.height > png.width / 2


def _png(width, height, fmt="PNG"):
    out = io.BytesIO()
    Image.new("RGB", (width, height), (15, 118, 110)).save(out, fmt)
    return out.getvalue()


def test_uploaded_images_are_re_encoded_and_bounded():
    big = images.normalize(_png(3000, 1000, fmt="JPEG"), AssetKind.LOGO)
    assert (big.width, big.height) == (1200, 400)  # shrunk to the print size
    assert big.png.startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(images.ImageRejected, match="too small"):
        images.normalize(_png(120, 40), AssetKind.LOGO)
    assert images.normalize(_png(160, 60), AssetKind.SIGNATURE).width == 160
    with pytest.raises(images.ImageRejected, match="PNG, JPEG or WebP"):
        images.normalize(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', AssetKind.LOGO)
    with pytest.raises(images.ImageRejected, match="2 MB"):
        images.normalize(b"\x89PNG" + b"0" * images.MAX_UPLOAD_BYTES, AssetKind.LOGO)
