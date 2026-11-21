"""Frozen shape of the extraction schema (I0)."""

import pytest

from core.extract.schema import FIELDS, SchemaError, json_schema, validate


def _good() -> dict[str, object]:
    values: dict[str, object] = {
        "sender": "Max Mustermann GmbH",
        "date": "2025-01-31",
        "amount": "12.50",
        "currency": "EUR",
        "deadline": None,
        "doc_type": "rechnung",
    }
    return {**values, "confidence": dict.fromkeys(FIELDS, 0.9)}


def test_schema_lists_fields() -> None:
    props = json_schema()["properties"]
    assert set(FIELDS) | {"confidence"} == set(props)


def test_validate_accepts_good() -> None:
    validate(_good())


@pytest.mark.parametrize("key,value", [("doc_type", "other"), ("confidence", {"sender": 2})])
def test_validate_rejects_bad(key: str, value: object) -> None:
    data = _good()
    data[key] = value
    with pytest.raises(SchemaError):
        validate(data)
