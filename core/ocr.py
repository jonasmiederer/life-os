"""Local OCR through the tesseract command line (deu+eng). PDFs go through pdftoppm first.

Text stays on the host. Nothing here logs text.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

LANGS = "deu+eng"
PDF_DPI = "200"
MAX_PDF_PAGES = 30


class OcrError(RuntimeError):
    """OCR failed. The message never contains document text."""


class TesseractMissing(OcrError):
    """The tesseract binary (or pdftoppm for PDFs) is not installed."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str


@dataclass(frozen=True)
class OcrResult:
    pages: list[PageText]
    extractor: str = "tesseract"
    model_id: str = f"tesseract-{LANGS}"

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def _need(binary: str) -> str:
    found = shutil.which(binary)
    if found is None:
        raise TesseractMissing(f"{binary} is not installed")
    return found


def _run(cmd: list[str], timeout: int) -> str:
    try:
        res = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError("ocr timed out") from exc
    if res.returncode != 0:
        raise OcrError(f"{Path(cmd[0]).name} exited with {res.returncode}")
    return res.stdout


def _tesseract(image: Path, timeout: int) -> str:
    return _run([_need("tesseract"), str(image), "stdout", "-l", LANGS], timeout)


def ocr_file(path: Path, timeout: int = 120) -> OcrResult:
    """OCR one PNG, JPEG or PDF. Raises TesseractMissing or OcrError."""
    _need("tesseract")
    if path.suffix.lower() != ".pdf":
        return OcrResult([PageText(1, _tesseract(path, timeout).strip())])
    pdftoppm = _need("pdftoppm")
    with tempfile.TemporaryDirectory() as tmp:
        _run(
            [pdftoppm, "-r", PDF_DPI, "-l", str(MAX_PDF_PAGES), "-png", str(path), f"{tmp}/p"],
            timeout,
        )
        images = sorted(Path(tmp).glob("p-*.png"))
        if not images:
            raise OcrError("pdf has no pages")
        return OcrResult(
            [PageText(i, _tesseract(img, timeout).strip()) for i, img in enumerate(images, 1)]
        )
