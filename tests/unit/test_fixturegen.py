from __future__ import annotations

from pathlib import Path

from scripts.check_fixtures_clean import scan
from tests.fixturegen.gen import generate


def test_generated_fixtures_are_clean(tmp_path: Path) -> None:
    assert len(generate(tmp_path)) == 6
    assert scan(tmp_path) == []
