"""Extraction result for one document (design 2.7). Frozen skeleton (I0).

Fields: sender, date, amount, currency, deadline, doc_type, plus one
confidence per field. A missing value is None, never a guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOC_TYPES: tuple[str, ...] = (
    "steuerbescheid",
    "rechnung",
    "mahnung",
    "kuendigung_vertrag",
    "versicherung",
    "sonstiges",
)

FIELDS: tuple[str, ...] = ("sender", "date", "amount", "currency", "deadline", "doc_type")

_VALUE: dict[str, dict[str, Any]] = {
    "sender": {"type": ["string", "null"]},
    "date": {"type": ["string", "null"], "format": "date"},
    "amount": {"type": ["string", "null"], "description": "Decimal as string, e.g. 12.50"},
    "currency": {"type": ["string", "null"], "pattern": "^[A-Z]{3}$"},
    "deadline": {"type": ["string", "null"], "format": "date"},
    "doc_type": {"enum": [*DOC_TYPES, None]},
}

JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ExtractionResult",
    "type": "object",
    "additionalProperties": False,
    "required": [*FIELDS, "confidence"],
    "properties": {
        **_VALUE,
        "confidence": {
            "type": "object",
            "additionalProperties": False,
            "required": list(FIELDS),
            "properties": {f: {"type": "number", "minimum": 0, "maximum": 1} for f in FIELDS},
        },
    },
}


class SchemaError(ValueError):
    """Extraction output does not match the schema."""


def json_schema() -> dict[str, Any]:
    """Return the JSON schema of one extraction result."""
    return JSON_SCHEMA


def validate(data: Mapping[str, Any]) -> None:
    """Check a parsed model output against the schema.

    Raises SchemaError on the first problem. Trivial on purpose: key set,
    doc_type and confidence range only. Replace with a full validator when
    the extraction work item lands.
    """
    if set(data) != set(JSON_SCHEMA["required"]):
        raise SchemaError("keys do not match schema")
    if data["doc_type"] not in (*DOC_TYPES, None):
        raise SchemaError("unknown doc_type")
    conf = data["confidence"]
    if not isinstance(conf, Mapping) or set(conf) != set(FIELDS):
        raise SchemaError("confidence keys do not match")
    for value in conf.values():
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise SchemaError("confidence must be a number from 0 to 1")
