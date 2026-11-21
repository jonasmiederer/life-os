"""evals-det stub (review-p0 35). Real OCR and extraction evals start in Phase 1a.

Placeholder check: the generator yields the expected number of synthetic files.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tests.fixturegen.gen import generate


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        n = len(generate(Path(d), count=3))
    print(f"evals-det (stub): {n} synthetic files")
    return 0 if n == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
