from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tests_layout() -> None:
    for name in ("unit", "contract", "security", "fixtures", "fixturegen"):
        assert (ROOT / "tests" / name).is_dir()
