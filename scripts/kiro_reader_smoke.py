"""Manual smoke test: ONE real Kiro call on a synthetic letter. Local use only, never CI.

Needs KIRO_API_KEY and LIFEOS_KIRO_MODEL in the environment. Prints pass/fail and
duration only, never the model output.
"""

from __future__ import annotations

import os
import sys
import time

from core.gateway.interface import GatewayError, GatewayRequest, PrivacyClass
from core.gateway.kiro import KiroBackend, KiroConfig

LETTER = """Beispielwerke AG
Rechnung vom 18.05.2030 an Max Mustermann
Betrag: 592,97 EUR. Zahlbar bis 01.06.2030.
"""


def main() -> int:
    model = os.environ.get("LIFEOS_KIRO_MODEL", "")
    if not model:
        print("set LIFEOS_KIRO_MODEL")
        return 2
    backend = KiroBackend(KiroConfig(model=model))
    req = GatewayRequest("smoke-1", PrivacyClass.ALLOW, "extract", LETTER)
    start = time.monotonic()
    try:
        backend.run(req)
    except GatewayError as exc:
        print(f"FAIL {type(exc).__name__} {time.monotonic() - start:.1f}s")
        return 1
    print(f"PASS {time.monotonic() - start:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
