"""Synthetic invoice scans: PNG and PDF with a sidecar ground-truth JSON.

Deterministic by seed. Reserved values only (Mustermann, example.com, IBAN check digits 00).
Layout is invented here, never copied from a real letter.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from tests.fixturegen.gen import IBAN, MARKER

SIZE = (420, 594)  # A-series ratio, small on purpose
VARIANTS = ("clean", "noise", "rotated", "lowcontrast", "combined")
SENDERS = ("Musterfirma GmbH", "Beispielwerke AG", "Testhandel KG", "Demo Dienste GmbH")
PDF_DATE = time.gmtime(1893456000)  # 2030-01-01  # fixed so PDFs are reproducible
FIELDS = ("sender", "date", "amount", "currency", "deadline", "doc_type")


def truth(seed: int) -> dict[str, str]:
    """Ground truth for one invoice. Same field names as the extractor contract."""
    rng = random.Random(seed)
    date = dt.date(2030, 1, 1) + dt.timedelta(days=rng.randrange(0, 700))
    return {
        "sender": SENDERS[seed % len(SENDERS)],
        "date": date.isoformat(),
        "amount": f"{rng.randrange(10, 900)}.{rng.randrange(0, 100):02d}",
        "currency": "EUR",
        "deadline": (date + dt.timedelta(days=rng.choice((14, 21, 30)))).isoformat(),
        "doc_type": "invoice",
    }


def _lines(t: dict[str, str], seed: int) -> list[str]:
    amount = t["amount"].replace(".", ",")
    return [
        t["sender"],
        "Beispielweg 2, 54321 Beispielort",
        "",
        "Max Mustermann",
        "Musterstrasse 1",
        "12345 Musterstadt",
        "",
        f"Datum: {t['date']}",
        f"Rechnung Nr. RE-{seed:05d}",
        "",
        f"Rechnungsbetrag: {amount} EUR",
        f"Zahlbar bis: {t['deadline']}",
        f"IBAN: {IBAN}",
        "Kontakt: service@example.com",
    ]


def _noise(rng: random.Random, strength: int) -> Image.Image:
    raw = bytes(128 + rng.randrange(-strength, strength + 1) for _ in range(SIZE[0] * SIZE[1]))
    return Image.frombytes("L", SIZE, raw)


def render(seed: int, variant: str) -> tuple[Image.Image, dict[str, str]]:
    """Render one grayscale page and return it with its ground truth."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    t = truth(seed)
    rng = random.Random(f"{seed}:{variant}")
    ink = 150 if variant in ("lowcontrast", "combined") else 20
    paper = 215 if variant in ("lowcontrast", "combined") else 250
    img = Image.new("L", SIZE, paper)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    y = 40
    for i, line in enumerate(_lines(t, seed)):
        draw.text((30, y), line, fill=ink, font=font)
        y += 24 if i else 28
    if variant in ("rotated", "combined"):
        angle = rng.uniform(-3.0, 3.0)
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=paper)
    if variant in ("noise", "combined"):
        img = ImageChops.add(img, _noise(rng, 20), scale=1.0, offset=-128)
    return img, t


def write_one(out: Path, seed: int, variant: str, fmt: str) -> Path:
    """Write `<variant>-<seed>.<fmt>` plus its `.json` sidecar. Returns the image path."""
    if fmt not in ("png", "pdf"):
        raise ValueError(f"unknown format: {fmt}")
    out.mkdir(parents=True, exist_ok=True)
    img, t = render(seed, variant)
    path = out / f"invoice-{variant}-{seed}.{fmt}"
    if fmt == "png":
        img.save(path, format="PNG", optimize=True)
    else:
        img.save(
            path,
            format="PDF",
            resolution=72.0,
            quality=60,
            creationDate=PDF_DATE,
            modDate=PDF_DATE,
        )
    side = {
        "marker": MARKER,
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "seed": seed,
        "variant": variant,
        **t,
    }
    sidecar_path(path).write_text(json.dumps(side, indent=2, sort_keys=True) + "\n", "utf-8")
    return path


def sidecar_path(image: Path) -> Path:
    return image.with_name(image.name + ".json")


def generate_images(out: Path, seed: int = 1) -> list[Path]:
    """Each variant as PNG and PDF: 10 images, 10 sidecars."""
    paths: list[Path] = []
    for i, variant in enumerate(VARIANTS):
        for fmt in ("png", "pdf"):
            paths.append(write_one(out, seed + i, variant, fmt))
    return paths


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/letters")
    for p in generate_images(target):
        print(p)
