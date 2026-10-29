"""
HTML (Jinja2) to PDF (WeasyPrint), with nothing reaching outside the process.

- Autoescaping is on, and every value is data: no one supplies HTML or CSS.
- The URL fetcher refuses every URL except embedded data (logos, signatures) and the bundled
  fonts, so a value can never make the renderer read a file or call a server.
- The fonts are bundled (hrms/assets/fonts), so every server prints identical PDFs, with ₹.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

from jinja2 import Environment, PackageLoader, StrictUndefined

import hrms
from hrms.modules.payroll.payslip.document import PayslipView

FONTS_DIR = (Path(hrms.__file__).parent / "assets" / "fonts").resolve()
# The setup preview's width in pixels: sharp on a high-density screen at about 620 CSS pixels.
PREVIEW_WIDTH = 1240
PAGE_GAP = 16

_env = Environment(
    loader=PackageLoader("hrms.modules.payroll.payslip", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["days"] = lambda v: f"{Decimal(v).normalize():f}"


def bundled_only_fetcher():
    """A URL fetcher for embedded data and the bundled fonts; everything else is refused."""
    # WeasyPrint loads Pango when imported: imported here, so a server without Pango still
    # starts, and only PDF rendering fails.
    from weasyprint.urls import URLFetcher

    class BundledOnly(URLFetcher):
        def __init__(self) -> None:
            super().__init__(timeout=2, allowed_protocols=("data", "file"), allow_redirects=False)

        def fetch(self, url, headers=None):
            if url.startswith("file:"):
                path = Path(unquote(urlparse(url).path)).resolve()
                if not path.is_relative_to(FONTS_DIR):
                    raise ValueError(f"refused: {url}")
            return super().fetch(url, headers)

    return BundledOnly()


def render_html(view: PayslipView) -> str:
    return _env.get_template("payslip.html.j2").render(view=view)


def _document(view: PayslipView):
    from weasyprint import HTML

    return HTML(
        string=render_html(view),
        base_url=FONTS_DIR.as_uri() + "/",
        url_fetcher=bundled_only_fetcher(),
    )


def page_count(view: PayslipView) -> int:
    return len(_document(view).render().pages)


def render_pdf(view: PayslipView) -> bytes:
    """The payslip as a PDF. Blocking (about 0.15 s): call through run_in_threadpool."""
    return _document(view).write_pdf()


def render_png(view: PayslipView, width: int = PREVIEW_WIDTH) -> bytes:
    """
    The payslip as one PNG, its pages one under the other: the setup preview. An image shows
    the same in every browser, including phones, which don't display PDFs inline. Blocking.
    """
    import pypdfium2 as pdfium
    from PIL import Image

    document = pdfium.PdfDocument(render_pdf(view))
    try:
        pages = [page.render(scale=width / page.get_size()[0]).to_pil() for page in document]
    finally:
        document.close()
    height = sum(p.height for p in pages) + PAGE_GAP * (len(pages) - 1)
    sheet = Image.new("RGB", (max(p.width for p in pages), height), (229, 231, 235))
    top = 0
    for page in pages:
        sheet.paste(page, (0, top))
        top += page.height + PAGE_GAP
    out = io.BytesIO()
    sheet.save(out, "PNG")
    return out.getvalue()
