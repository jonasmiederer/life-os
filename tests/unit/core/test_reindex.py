"""synthetic: true"""

from pathlib import Path

import pytest

from core.reindex import cache_dir, reindex
from core.synthetic import populate


def test_fallback_listing_and_rebuild(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.reindex.shutil.which", lambda _name: None)  # no qmd
    root = tmp_path / "data"
    populate(root)
    stale = cache_dir(root) / "stale"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("x")
    assert reindex(root) == "listing"
    assert not stale.exists()  # cache was deleted
    listing = (cache_dir(root) / "listing.txt").read_text().splitlines()
    assert any(p.startswith("notes/") for p in listing)
    assert any(p.startswith("raw/") for p in listing)
