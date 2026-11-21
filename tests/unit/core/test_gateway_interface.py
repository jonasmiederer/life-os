"""Frozen shape of the gateway interface (I0)."""

from core.gateway.interface import (
    AuthExpired,
    Backend,
    BackendUnavailable,
    Blocked,
    GatewayError,
    GatewayRequest,
    GatewayResult,
    InvalidOutput,
    NotSupported,
    PrivacyClass,
)


def test_privacy_classes() -> None:
    assert {c.value for c in PrivacyClass} == {"allow", "block", "local", "redacted"}


def test_errors_share_base() -> None:
    for err in (NotSupported, BackendUnavailable, AuthExpired, InvalidOutput, Blocked):
        assert issubclass(err, GatewayError)


def test_request_image_optional() -> None:
    req = GatewayRequest("doc-1", PrivacyClass.ALLOW, "extract", "Max Mustermann")
    assert req.image is None


def test_backend_protocol() -> None:
    class Fake:
        name = "fake"

        def run(self, request: GatewayRequest) -> GatewayResult:
            return GatewayResult({}, self.name, "m")

    assert isinstance(Fake(), Backend)
