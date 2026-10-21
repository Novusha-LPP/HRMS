"""Profile photo thumbnails.

A person's profile photo is their KYC document of type PHOTO. Avatars are small, but the photos
people upload are often several megabytes, so the app is served a square JPEG thumbnail made
once and kept (encrypted, like every document) next to the original.

The image is untrusted input: it is decoded under a pixel limit, orientation is applied, and
anything that cannot be decoded safely simply has no thumbnail (the app then shows initials).
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

THUMB_PIXELS = 192
LARGE_PIXELS = 640
# A 12-megapixel phone photo is about 12 million; this refuses image-bomb sized inputs outright.
MAX_PIXELS = 50_000_000
JPEG_QUALITY = 82

PHOTO_TYPE = "PHOTO"


def thumbnail_ref(tenant_id, document_id) -> str:
    """Where a document's thumbnail is kept (the reference the document store understands)."""
    return f"doc:kyc/{tenant_id}/thumb/{document_id}.jpg"


def large_ref(tenant_id, document_id) -> str:
    """Where the larger view of a photo is kept."""
    return f"doc:kyc/{tenant_id}/large/{document_id}.jpg"


def _render(data: bytes, pixels: int, *, square: bool) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                return None
            if opened.format == "JPEG":
                # Decode at reduced size: much faster and lighter for large photographs.
                opened.draft("RGB", (pixels * 2, pixels * 2))
            upright = ImageOps.exif_transpose(opened)
            if upright.mode in ("RGBA", "LA", "P"):
                rgba = upright.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, (255, 255, 255))
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = upright.convert("RGB")
            if square:
                out_image = ImageOps.fit(
                    rgb, (pixels, pixels), Image.Resampling.LANCZOS, centering=(0.5, 0.4)
                )
            else:
                # The whole picture, never enlarged and never cropped.
                out_image = rgb.copy()
                out_image.thumbnail((pixels, pixels), Image.Resampling.LANCZOS)  # shrinks only
            out = io.BytesIO()
            out_image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None


def make_thumbnail(data: bytes) -> bytes | None:
    """A square THUMB_PIXELS JPEG of the image, or None if it cannot be decoded safely."""
    return _render(data, THUMB_PIXELS, square=True)


def make_large(data: bytes) -> bytes | None:
    """The whole picture, at most LARGE_PIXELS on its longer side, or None if undecodable."""
    return _render(data, LARGE_PIXELS, square=False)
