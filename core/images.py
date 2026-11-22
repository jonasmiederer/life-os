"""Re-encode uploaded images so no EXIF, GPS or other metadata is stored in files/.

HEIC (iPhone default) becomes PNG. JPEG stays JPEG, PNG stays PNG. The pixels are copied
into a fresh image, so no metadata block can ride along. PDFs are not touched here.
shortcut: PDF metadata (author, producer) is kept, strip it with the PDF handling item.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

MAX_PIXELS = 100_000_000  # about 10000 x 10000, guards against decompression bombs
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}


class BadImage(ValueError):
    """The bytes are not a readable image."""


def is_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS


def clean_image(data: bytes, ext: str) -> tuple[bytes, str]:
    """Return (bytes, ext) with metadata removed and orientation applied to the pixels."""
    if ext == "heic":
        import pillow_heif  # noqa: PLC0415 - only needed for HEIC

        pillow_heif.register_heif_opener()
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(io.BytesIO(data)) as src:
            if src.width * src.height > MAX_PIXELS:
                raise BadImage("image too large")
            upright = ImageOps.exif_transpose(src)
            fresh = Image.frombytes(upright.mode, upright.size, upright.tobytes())
        out = io.BytesIO()
        if ext == "jpg":
            if fresh.mode not in ("RGB", "L"):
                fresh = fresh.convert("RGB")
            fresh.save(out, "JPEG", quality=95)
            return out.getvalue(), "jpg"
        fresh.save(out, "PNG")
        return out.getvalue(), "png"
    except BadImage:
        raise
    except Exception as exc:  # noqa: BLE001 - Pillow and heif raise many types on bad input
        raise BadImage("unreadable image") from exc
