"""Per-field scorer for document extraction (E1b). Stable API for the eval harness and spikes.

Public functions:
  normalize(field, value)        -> canonical string or None
  score_docs(pairs)              -> {field: FieldScore-dict} plus "micro" over all fields
  cer(hypothesis, reference)     -> character error rate (edit distance / len(reference))
  failing_fields(scores, floor)  -> text safe for logs: field names and numbers only

Conventions, per field and document (truth t, prediction p, after normalize):
  t and p equal and not None -> tp
  t None, p not None         -> fp
  t not None, p None         -> fn
  both not None and differ   -> fp and fn (a wrong value is a false alarm and a miss)
  both None                  -> nothing (a correct "not present")
Nothing here returns or prints document text. Inputs are dicts with the FIELDS keys
(extra keys such as confidence are ignored); a missing key counts as None.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

FIELDS: tuple[str, ...] = ("sender", "date", "amount", "currency", "deadline", "doc_type")

# Ground truth from the fixture generator says "invoice"; the schema says "rechnung".
_DOC_TYPE_ALIASES = {"invoice": "rechnung", "bill": "rechnung"}
_CURRENCY_SYMBOLS = {"€": "EUR", "eur": "EUR", "euro": "EUR"}
_DMY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def _date(raw: str) -> str | None:
    m = _DMY.match(raw)
    try:
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return None


def _amount(raw: str) -> str | None:
    s = re.sub(r"[^\d.,-]", "", raw)
    if "," in s and "." in s:  # the last separator is the decimal one
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    else:
        s = s.replace(",", ".")
    try:
        return f"{Decimal(s):.2f}"
    except InvalidOperation:
        return None


def normalize(field: str, value: Any) -> str | None:
    """Canonical form of one value. Empty or unparseable input gives None."""
    if field not in FIELDS:
        raise ValueError(f"unknown field: {field}")
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if field in ("date", "deadline"):
        return _date(raw)
    if field == "amount":
        return _amount(raw)
    if field == "currency":
        low = raw.casefold()
        return _CURRENCY_SYMBOLS.get(low) or raw.upper()
    low = " ".join(raw.casefold().split())
    if field == "doc_type":
        return _DOC_TYPE_ALIASES.get(low, low)
    return re.sub(r"[^\w ]", "", low).strip() or None  # sender


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f1, 4),
    }


def score_docs(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, dict[str, float | int]]:
    """Score (prediction, truth) pairs. Returns per-field counts, precision, recall, F1.

    The extra key "micro" sums the counts over all fields. If no document has a value
    for a field, its scores are 0.0 and its counts are 0.
    """
    counts = {f: [0, 0, 0] for f in FIELDS}
    n = 0
    for pred, truth in pairs:
        n += 1
        for f in FIELDS:
            p, t = normalize(f, pred.get(f)), normalize(f, truth.get(f))
            if t is not None and p == t:
                counts[f][0] += 1
            else:
                if p is not None:
                    counts[f][1] += 1
                if t is not None:
                    counts[f][2] += 1
    out: dict[str, dict[str, float | int]] = {f: _prf(*c) for f, c in counts.items()}
    out["micro"] = _prf(*(sum(c[i] for c in counts.values()) for i in range(3)))
    out["micro"]["docs"] = n
    return out


def cer(hypothesis: str, reference: str) -> float:
    """Character error rate: Levenshtein distance divided by len(reference).

    Empty reference gives 0.0 for an empty hypothesis, else 1.0. Can exceed 1.0.
    """
    if not reference:
        return 0.0 if not hypothesis else 1.0
    prev = list(range(len(hypothesis) + 1))
    for i, rc in enumerate(reference, 1):
        cur = [i]
        for j, hc in enumerate(hypothesis, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return round(prev[-1] / len(reference), 4)


def failing_fields(
    scores: Mapping[str, Mapping[str, Any]], floor: Mapping[str, float]
) -> list[str]:
    """Lines "field f1=0.50 floor=0.90" for fields below their floor. No document text."""
    return [
        f"{f} f1={scores[f]['f1']:.2f} floor={v:.2f}"
        for f, v in floor.items()
        if f in scores and scores[f]["f1"] < v - 1e-9
    ]
