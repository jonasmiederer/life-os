from __future__ import annotations

from scripts.set_required_checks import CHECKS, with_checks


def test_with_checks_replaces_only_the_check_list() -> None:
    rs = {
        "name": "main-protect",
        "target": "branch",
        "enforcement": "active",
        "conditions": {},
        "bypass_actors": [],
        "id": 1,
        "rules": [
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "secrets-scan"}]},
            },
        ],
    }
    body = with_checks(rs, CHECKS)
    assert "id" not in body
    assert body["rules"][0] == {"type": "deletion"}
    got = [c["context"] for c in body["rules"][1]["parameters"]["required_status_checks"]]
    assert got == CHECKS
    assert len(CHECKS) == 10
