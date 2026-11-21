"""Class routing: the gateway decides, the backend only runs (design 2.13)."""

from __future__ import annotations

import re
import time

from core.gateway.audit import AuditLog
from core.gateway.interface import (
    Backend,
    Blocked,
    GatewayError,
    GatewayRequest,
    GatewayResult,
    PrivacyClass,
)

# shortcut: small keyword list, German health and ID terms. Extend with the classifier item.
_BLOCK_KEYWORDS = re.compile(
    r"arzt|diagnose|krankenkasse|krankenhaus|patient|rezept|befund|"
    r"personalausweis|reisepass|ausweisnummer|f[uü]hrerschein",
    re.IGNORECASE,
)


def intake_class(text: str, *, local_only: bool, default: PrivacyClass) -> PrivacyClass:
    """Provisional class before any cloud call (design 2.13, step 2).

    "nur lokal" -> LOCAL. Health or ID keyword -> BLOCK. Nothing matched -> default,
    which the caller reads from the class switch (policy.toml).
    """
    if local_only:
        return PrivacyClass.LOCAL
    if _BLOCK_KEYWORDS.search(text):
        return PrivacyClass.BLOCK
    return default


class Gateway:
    def __init__(self, backend: Backend, audit: AuditLog) -> None:
        self._backend = backend
        self._audit = audit

    def run(self, request: GatewayRequest) -> GatewayResult:
        cls = request.privacy_class
        if cls in (PrivacyClass.BLOCK, PrivacyClass.LOCAL):
            raise Blocked(f"class switch is {cls.value}")  # zero cloud calls, no audit line
        if cls is PrivacyClass.REDACTED:
            raise NotImplementedError("redacted mode is not implemented in phase 1a")
        start = time.monotonic()
        model = str(getattr(self._backend, "model_id", "unknown"))
        outcome = "ok"
        try:
            return self._backend.run(request)
        except GatewayError as exc:
            outcome = type(exc).__name__
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            self._audit.write(
                doc_id=request.doc_id,
                privacy_class=cls.value,
                purpose=request.purpose,
                backend=self._backend.name,
                model=model,
                duration_ms=int((time.monotonic() - start) * 1000),
                outcome=outcome,
            )
