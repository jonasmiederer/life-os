"""Synthetic fixtures generated at runtime. No real data, no committed binaries.

synthetic: true
"""

from __future__ import annotations

import hashlib
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from core.datadir import init_data_dir
from core.store import write_note

LETTER = (
    "synthetic: true\n"
    "Finanzamt Musterstadt\nMusterstrasse 1\n12345 Musterstadt\n\n"
    "An Max Mustermann\n\nSteuerbescheid 2025 vom 03.11.2026\n"
    "Einspruch bis 07.12.2026. Nachzahlung 412,50 EUR.\n"
)


def synthetic_eml() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Max Mustermann <max@example.com>"
    msg["To"] = "ingest@example.com"
    msg["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    msg["Subject"] = "Fwd: Rechnung Musterfirma"
    msg.set_content("synthetic: true\nRechnung 99,00 EUR, zahlbar bis 20.11.2026.\n")
    return msg.as_bytes()


def _store_original(root: Path, year: str, slug: str, ext: str, data: bytes) -> str:
    rel = f"files/{year}/{slug}.{ext}"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    return rel


def _slug(day: str, sender: str, kind: str, data: bytes) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    return f"{day}-{sender}-{kind}-{sha[:8]}", sha


def populate(root: Path) -> dict[str, Any]:
    """Create one letter note and one .eml note through the normal write path (no OCR)."""
    init_data_dir(root)
    out: dict[str, Any] = {}
    letter = LETTER.encode()
    slug, sha = _slug("2026-11-03", "finanzamt-musterstadt", "steuerbescheid", letter)
    rel = _store_original(root, "2026", slug, "pdf", letter)
    out["letter"] = (
        slug,
        write_note(
            root,
            slug,
            {
                "type": "steuerbescheid",
                "from": "Finanzamt Musterstadt",
                "date": date(2026, 11, 3),
                "deadline": date(2026, 12, 7),
                "deadline_kind": "einspruch",
                "amount": 412.5,
                "status": "draft",
                "source": "upload",
                "raw": f"raw/{slug}.md",
            },
            "Synthetic summary.\n",
            {"file": rel, "sha256": sha, "pages": 1, "extractor": "tesseract", "model_id": "none"},
            LETTER,
        ),
    )
    eml = synthetic_eml()
    slug, sha = _slug("2026-11-03", "musterfirma", "rechnung", eml)
    rel = _store_original(root, "2026", slug, "eml", eml)
    out["eml"] = (
        slug,
        write_note(
            root,
            slug,
            {
                "type": "rechnung",
                "from": "Musterfirma",
                "date": date(2026, 11, 3),
                "deadline": date(2026, 11, 20),
                "deadline_kind": "zahlung",
                "amount": 99.0,
                "status": "draft",
                "source": "mail",
                "raw": f"raw/{slug}.md",
            },
            "Synthetic summary.\n",
            {"file": rel, "sha256": sha, "pages": 1, "extractor": "tesseract", "model_id": "none"},
            "synthetic: true\nRechnung 99,00 EUR.\n",
        ),
    )
    return out


def populate_invalid(root: Path) -> list[str]:
    """Write one note with an unknown frontmatter key. It must land in review/."""
    slug = "2026-11-04-musterfirma-rechnung-deadbeef"
    return write_note(
        root,
        slug,
        {
            "type": "rechnung",
            "from": "Musterfirma",
            "date": date(2026, 11, 4),
            "status": "draft",
            "source": "upload",
            "raw": f"raw/{slug}.md",
            "surprise": "x",
        },
        "Synthetic.\n",
        {
            "file": f"files/2026/{slug}.pdf",
            "sha256": "0" * 64,
            "pages": 1,
            "extractor": "tesseract",
            "model_id": "none",
        },
        "synthetic: true\n",
    )
