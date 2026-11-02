"""Logo and signature uploads.

An uploaded image is untrusted input. It is decoded under a pixel limit and re-encoded as a
fresh PNG, which drops metadata and anything else hidden in the file, keeps transparency, and
caps the size printed into PDFs. SVG is refused: it can reference external files.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from hrms.modules.branding.models import AssetKind

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 20_000_000
ACCEPTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
# The longer side: at least this many pixels, so the image stays sharp in print...
MIN_SIDE = {AssetKind.LOGO: 200, AssetKind.SIGNATURE: 150}
# ...and at most this many, so PDFs stay small.
MAX_SIDE = {AssetKind.LOGO: 1200, AssetKind.SIGNATURE: 800}


class ImageRejected(ValueError):
    """The upload is not an image this app accepts; the message says why, for the user."""


@dataclass(frozen=True)
class NormalizedImage:
    png: bytes
    width: int
    height: int


def normalize(data: bytes, kind: AssetKind) -> NormalizedImage:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected("The image is larger than 2 MB. Upload a smaller file.")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.format not in ACCEPTED_FORMATS:
                raise ImageRejected("Upload a PNG, JPEG or WebP image.")
            if opened.width * opened.height > MAX_PIXELS:
                raise ImageRejected("The image has too many pixels. Upload a smaller one.")
            image = ImageOps.exif_transpose(opened).convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ImageRejected("The file is not a readable PNG, JPEG or WebP image.") from exc
    if max(image.size) < MIN_SIDE[kind]:
        raise ImageRejected(
            f"The image is too small to print sharply: make its longer side at least "
            f"{MIN_SIDE[kind]} pixels."
        )
    image.thumbnail((MAX_SIDE[kind], MAX_SIDE[kind]), Image.Resampling.LANCZOS)  # shrinks only
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return NormalizedImage(png=out.getvalue(), width=image.width, height=image.height)
