"""evals-det: score a deterministic rule baseline on the synthetic letters (E1b).

SYNTHETIC, RULE BASELINE, NOT MODEL QUALITY. The numbers say the harness and the
rules work on clean generated text. They say nothing about Kiro or Tesseract.

Offline. No network, no secret, no OCR binary: the text comes from the fixture
generator's own line layout (the "sidecar text path"), not from the image pixels.
A later step plugs real OCR in here. Failure output has field names and scores only.

  python -m evals.det.run            compare with evals/baselines/det-rule.json
  python -m evals.det.run --write    rewrite that file (high-risk path, owner reviews)
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

from evals.score import FIELDS, cer, failing_fields, score_docs
from tests.fixturegen.images import _lines

ROOT = Path(__file__).resolve().parents[2]
LETTERS = ROOT / "tests" / "fixtures" / "letters"
BASELINE = ROOT / "evals" / "baselines" / "det-rule.json"
LABEL = "synthetic, rule baseline, not model quality"
_RULES = {
    "date": re.compile(r"^Datum:\s*(\S+)", re.M),
    "amount": re.compile(r"^Rechnungsbetrag:\s*([\d.,]+)\s*([A-Z]{3})", re.M),
    "deadline": re.compile(r"^Zahlbar bis:\s*(\S+)", re.M),
    "doc_type": re.compile(r"^(Rechnung) Nr\.", re.M),
}


def extract(text: str) -> dict[str, str | None]:
    """Rule extractor: first line is the sender, labelled lines give the rest."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
    out: dict[str, str | None] = {f: None for f in FIELDS}
    out["sender"] = first
    for field, rx in _RULES.items():
        m = rx.search(text)
        if m:
            out[field] = m[1].lower() if field == "doc_type" else m[1]
            if field == "amount":
                out["currency"] = m[2]
    return out


_CONFUSE = {"0": "O", "1": "l", "5": "S", "8": "B", ",": "."}


def degrade(text: str, key: str, rate: float = 0.06) -> str:
    """Seeded OCR-like character swaps. Stand-in for a noisy scan, not a real OCR model."""
    rng = random.Random(key)  # noqa: S311  # nosec B311: deterministic test data
    return "".join(_CONFUSE[c] if c in _CONFUSE and rng.random() < rate else c for c in text)


def run(letters: Path = LETTERS) -> dict[str, object]:
    """Two sets of text: "clean" (exact lines) and "degraded" (seeded swaps, with CER)."""
    pairs: dict[str, list] = {"clean": [], "degraded": []}  # type: ignore[type-arg]
    cers = []
    for side in sorted(letters.glob("*.png.json")):
        truth = json.loads(side.read_text("utf-8"))
        text = "\n".join(_lines(truth, truth["seed"]))
        noisy = degrade(text, side.name)
        pairs["clean"].append((extract(text), truth))
        pairs["degraded"].append((extract(noisy), truth))
        cers.append(cer(noisy, text))
    return {
        "label": LABEL,
        "text_source": "fixture generator lines",
        "scores": score_docs(pairs["clean"]),
        "degraded_scores": score_docs(pairs["degraded"]),
        "degraded_mean_cer": round(sum(cers) / len(cers), 4) if cers else None,
    }


def main(argv: list[str]) -> int:
    result = run()
    if "--write" in argv:
        BASELINE.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"wrote baseline ({LABEL})")
        return 0
    base = json.loads(BASELINE.read_text("utf-8"))
    bad = []
    for key in ("scores", "degraded_scores"):
        floor = {f: base[key][f]["f1"] for f in (*FIELDS, "micro")}
        bad += [f"{key} {x}" for x in failing_fields(result[key], floor)]  # type: ignore[arg-type]
    clean, noisy = result["scores"], result["degraded_scores"]
    n = clean["micro"]["docs"]  # type: ignore[index]
    print(
        f"evals-det ({LABEL}): {n} docs, micro f1 clean={clean['micro']['f1']:.2f}"  # type: ignore[index]
        f" degraded={noisy['micro']['f1']:.2f}"  # type: ignore[index]
    )
    if n == 0:
        print("FAIL: no fixtures found")
        return 1
    for line in bad:
        print(f"FAIL {line}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
