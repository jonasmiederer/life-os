from __future__ import annotations

import pytest

from evals.det.run import BASELINE, degrade, extract, main
from evals.score import cer, failing_fields, normalize, score_docs

T = {
    "sender": "Musterfirma GmbH",
    "date": "2030-01-05",
    "amount": "12.50",
    "currency": "EUR",
    "deadline": None,
    "doc_type": "invoice",
}


@pytest.mark.parametrize(
    ("field", "raw", "want"),
    [
        ("date", "05.01.2030", "2030-01-05"),
        ("date", "2030-13-45", None),
        ("amount", "1.234,5", "1234.50"),
        ("amount", "12,50 EUR", "12.50"),
        ("amount", "abc", None),
        ("currency", "€", "EUR"),
        ("sender", "  Muster-Firma  GmbH ", "musterfirma gmbh"),
        ("doc_type", "Invoice", "rechnung"),
        ("sender", "", None),
    ],
)
def test_normalize(field: str, raw: str, want: str | None) -> None:
    assert normalize(field, raw) == want


def test_normalize_unknown_field() -> None:
    with pytest.raises(ValueError, match="unknown field"):
        normalize("iban", "x")


def test_perfect_prediction_ignores_extra_keys() -> None:
    s = score_docs([({**T, "doc_type": "rechnung", "confidence": {}}, T)])
    assert s["micro"]["f1"] == 1.0
    assert s["deadline"]["tp"] == 0  # correct "not present" counts for nothing


def test_wrong_value_is_fp_and_fn_missing_is_fn_extra_is_fp() -> None:
    pred = {**T, "amount": "99.00", "date": None, "deadline": "2030-02-01"}
    s = score_docs([(pred, T)])
    assert (s["amount"]["fp"], s["amount"]["fn"]) == (1, 1)
    assert (s["date"]["fp"], s["date"]["fn"]) == (0, 1)
    assert (s["deadline"]["fp"], s["deadline"]["fn"]) == (1, 0)
    assert s["amount"]["f1"] == 0.0


def test_partial_f1() -> None:
    good, bad = dict(T), {**T, "sender": "Other AG"}
    s = score_docs([(good, T), (bad, T)])
    assert s["sender"] == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }


def test_no_docs() -> None:
    assert score_docs([])["micro"]["docs"] == 0


def test_cer() -> None:
    assert cer("abc", "abc") == 0.0
    assert cer("abd", "abc") == pytest.approx(0.3333, abs=1e-4)
    assert cer("", "abc") == 1.0
    assert cer("", "") == 0.0


def test_failing_fields_prints_no_text() -> None:
    out = failing_fields({"sender": {"f1": 0.5}}, {"sender": 1.0, "date": 1.0})
    assert out == ["sender f1=0.50 floor=1.00"]


def test_extract_and_degrade_are_deterministic() -> None:
    text = "Musterfirma GmbH\nDatum: 2030-01-05\nRechnung Nr. RE-1\nRechnungsbetrag: 12,50 EUR\n"
    got = extract(text)
    assert (got["sender"], got["amount"], got["currency"], got["doc_type"]) == (
        "Musterfirma GmbH",
        "12,50",
        "EUR",
        "rechnung",
    )
    assert degrade(text, "k") == degrade(text, "k")


def test_det_run_passes_against_committed_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    assert BASELINE.exists()
    assert main([]) == 0
    assert "not model quality" in capsys.readouterr().out
