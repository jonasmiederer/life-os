"""Fake backend for tests of other work items. Canned outputs keyed by doc_id."""

from __future__ import annotations

from core.extract import schema
from core.gateway.interface import GatewayRequest, GatewayResult, InvalidOutput


class FakeBackend:
    name = "fake"
    model_id = "fake-1"

    def __init__(self, outputs: dict[str, dict[str, object]]) -> None:
        self._outputs = outputs
        self.calls = 0

    def run(self, request: GatewayRequest) -> GatewayResult:
        self.calls += 1
        data = self._outputs.get(request.doc_id)
        if data is None:
            raise InvalidOutput("no canned output for this doc_id")
        try:
            schema.validate(data)
        except schema.SchemaError:
            raise InvalidOutput("canned output does not match schema") from None
        return GatewayResult(data=dict(data), backend=self.name, model_id=self.model_id)
