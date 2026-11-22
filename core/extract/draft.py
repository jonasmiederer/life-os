"""Turn an extraction result into draft note frontmatter. Model output is untrusted.

Every value is parsed again here. A value that does not parse becomes missing,
never a guess (design 2.7).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from core.extract.schema import DOC_TYPES, SchemaError, validate
from core.schema import FROM_RE

UNKNOWN_SENDER = "unbekannt"
_DEADLINE_KIND = {
    "steuerbescheid": "einspruch",
    "rechnung": "zahlung",
    "mahnung": "zahlung",
    "kuendigung_vertrag": "kuendigung",
}
_NOT_FROM = re.compile(r"[^\w .,&@'()/-]")


@dataclass(frozen=True)
class DraftFields:
    doc_type: str = "sonstiges"
    sender: str = UNKNOWN_SENDER
    doc_date: date | None = None
    amount: str | None = None
    currency: str | None = None
    deadline: date | None = None

    @property
    def deadline_kind(self) -> str:
        if self.deadline is None:
            return "none"
        return _DEADLINE_KIND.get(self.doc_type, "other")


def _date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _amount(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        dec = Decimal(value)
    except InvalidOperation:
        return None
    return value if dec.is_finite() and len(value) <= 20 else None


def _sender(value: object) -> str:
    if not isinstance(value, str):
        return UNKNOWN_SENDER
    cleaned = " ".join(_NOT_FROM.sub("", value).split())[:120].strip()
    return cleaned if FROM_RE.match(cleaned) else UNKNOWN_SENDER


def from_extraction(data: Mapping[str, Any] | None) -> DraftFields:
    """Draft fields from validated model output. None or invalid output gives an empty draft."""
    if data is None:
        return DraftFields()
    try:
        validate(data)
    except SchemaError:
        return DraftFields()
    currency = data["currency"]
    return DraftFields(
        doc_type=data["doc_type"] if data["doc_type"] in DOC_TYPES else "sonstiges",
        sender=_sender(data["sender"]),
        doc_date=_date(data["date"]),
        amount=_amount(data["amount"]),
        currency=currency
        if isinstance(currency, str) and re.fullmatch("[A-Z]{3}", currency)
        else None,
        deadline=_date(data["deadline"]),
    )
