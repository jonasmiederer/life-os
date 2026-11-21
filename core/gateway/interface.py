"""Gateway interface: Backend protocol, request/result types, typed errors.

Frozen skeleton (I0). No logic. Owner of this file: the gateway work item.
Other work items import from here and do not edit it. See design 2.13.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class PrivacyClass(StrEnum):
    """Per-class cloud switch value from policy.toml (design 2.3, 2.13).

    allow: full text or image may go to the provider.
    block: nothing is processed beyond local OCR.
    local: stays on the host, local tools only.
    redacted: gateway masks identifiers in text before sending.
        Not implemented in Phase 1a: a gateway must raise NotImplementedError.
    """

    ALLOW = "allow"
    BLOCK = "block"
    LOCAL = "local"
    REDACTED = "redacted"


class GatewayError(Exception):
    """Base class of all typed gateway errors."""


class NotSupported(GatewayError):
    """The backend cannot do this, e.g. it has no image input."""


class BackendUnavailable(GatewayError):
    """The backend cannot be reached or is down."""


class AuthExpired(GatewayError):
    """The backend credential or sign-in is no longer valid."""


class InvalidOutput(GatewayError):
    """The model output did not validate against the schema. Drop it."""


class Blocked(GatewayError):
    """The class switch for this request is block or local."""


@dataclass(frozen=True)
class GatewayRequest:
    """One model call. Carries ids and class only, never logged content.

    doc_id: document id, used for the audit line.
    privacy_class: switch value that applies to this request.
    purpose: short fixed label, e.g. "extract".
    text: untrusted document text (always available from local OCR).
    image: optional page image bytes. A backend without image input
        raises NotSupported when this is set.
    """

    doc_id: str
    privacy_class: PrivacyClass
    purpose: str
    text: str
    image: bytes | None = None


@dataclass(frozen=True)
class GatewayResult:
    """Typed result of one model call.

    data: parsed JSON object, already checked against the schema.
    backend: backend name for the audit line.
    model_id: model identifier for the audit line.
    """

    data: dict[str, object]
    backend: str
    model_id: str


@runtime_checkable
class Backend(Protocol):
    """A model backend. Implementations hold no policy; the gateway does.

    Raises NotSupported, BackendUnavailable, AuthExpired or InvalidOutput.
    """

    name: str

    def run(self, request: GatewayRequest) -> GatewayResult:
        """Run one request and return a typed result."""
        ...
