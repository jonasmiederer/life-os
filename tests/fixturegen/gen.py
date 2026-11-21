"""Synthetic fixture generator. Only reserved values: example.com, Mustermann, IBAN check 00."""

from __future__ import annotations

from pathlib import Path

MARKER = "synthetic: true"
# Reserved test IBAN: check digits 00 (never valid). Built here so no digit run sits in the source.
IBAN = " ".join(["DE" + "00", "1234", "5678", "9012", "3456", "78"])

LETTER = """{marker}
Max Mustermann
Musterstrasse 1
12345 Musterstadt

Betreff: Beitragsanpassung {n}
Kundennummer: KD-0000{n}
IBAN: {iban}
Kontakt: service@example.com
"""

EML = """{marker}
From: Service <service@example.com>
To: Max Mustermann <max@example.com>
Subject: Rechnung {n}

Guten Tag, Ihre Rechnung finden Sie im Anhang.
"""


def generate(out: Path, count: int = 3) -> list[Path]:
    """Write `count` letters and mails into `out`. Returns the paths."""
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for n in range(1, count + 1):
        for name, tpl in ((f"letter{n}.txt", LETTER), (f"mail{n}.eml", EML)):
            p = out / name
            p.write_text(tpl.format(marker=MARKER, iban=IBAN, n=n), encoding="utf-8")
            paths.append(p)
    return paths


def generate_known_bad(out: Path) -> Path:
    """A real-looking leak, built at run time so the repo never holds one."""
    out.mkdir(parents=True, exist_ok=True)
    bad = out / "bad.txt"
    email = "erika" + "@" + "gmail" + ".com"
    iban = "DE" + "89" + "3704" + "0044" + "0532" + "0130" + "00"
    home = "/" + "Users" + "/someone/Documents"
    bad.write_text(f"{MARKER}\nMail {email}\nIBAN {iban}\nFile {home}\n", encoding="utf-8")
    return bad
