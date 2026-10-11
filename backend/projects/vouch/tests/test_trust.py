"""Tests for the Trust Center API router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vouch import main
from vouch.api.trust import _parse_cedar_policies
from vouch.audit import AuditStore
from vouch.service import VouchService


@pytest.fixture
def client(settings, tmp_path):
    settings = settings.model_copy(update={"data_dir": tmp_path, "seed_demo": False})
    service = VouchService(settings, store=AuditStore("sqlite://"), seed_demo=False, restore=False)
    service.seed(run_demo=False, background_vendors=0)
    main.set_service(service)
    try:
        yield TestClient(main.app)
    finally:
        main.set_service(None)


class TestCedarPolicyParser:
    """Tests for the Cedar policy parser."""

    def test_parse_cedar_policies_returns_9_rules(self):
        """Parser must find all 9 rules (P-01 through P-09) in vouch.cedar."""
        rules = _parse_cedar_policies()
        assert len(rules) == 9, f"Expected 9 rules, got {len(rules)}: {[r['id'] for r in rules]}"

    def test_parse_cedar_policies_all_ids_present(self):
        """All rule IDs P-01 through P-09 must be present."""
        rules = _parse_cedar_policies()
        ids = {r["id"] for r in rules}
        expected_ids = {f"P-{i:02d}" for i in range(1, 10)}
        assert ids == expected_ids, f"Missing IDs: {expected_ids - ids}, unexpected: {ids - expected_ids}"

    def test_parse_cedar_policies_id_order(self):
        """Rules should be returned in order P-01 through P-09."""
        rules = _parse_cedar_policies()
        ids = [r["id"] for r in rules]
        assert ids == [f"P-{i:02d}" for i in range(1, 10)]

    def test_parse_cedar_policies_descriptions_no_bleed(self):
        """Each rule's description must be its own comment, not the file header or another rule's."""
        rules = _parse_cedar_policies()
        rules_by_id = {r["id"]: r for r in rules}

        # P-03 should NOT have the file header (which mentions default deny, no permit for deny_vendor)
        p03 = rules_by_id["P-03"]
        assert p03["description"] is not None
        # The P-03 description should only be about automated system placing holds
        assert "hold" in p03["description"].lower() or "system" in p03["description"].lower()
        assert "default deny" not in p03["description"].lower(), "P-03 has file header as description"

        # P-04 description should NOT contain P-07's text about read/explain
        p04 = rules_by_id["P-04"]
        if p04["description"]:
            assert "read and explain" not in p04["description"].lower(), "P-04 has P-07's description"

        # P-07 should have its own description about read/explain
        p07 = rules_by_id["P-07"]
        assert p07["description"] is not None
        assert "read" in p07["description"].lower() or "explain" in p07["description"].lower()

    def test_parse_cedar_policies_effect_types(self):
        """All rules in vouch.cedar should be permit rules (no forbid)."""
        rules = _parse_cedar_policies()
        for rule in rules:
            assert rule["type"] == "permit", f"Rule {rule['id']} has unexpected type {rule['type']}"

    def test_parse_cedar_policies_principals(self):
        """Check that principals are correctly extracted."""
        rules = _parse_cedar_policies()
        rules_by_id = {r["id"]: r for r in rules}

        # Owner rules
        for pid in ["P-01", "P-02", "P-06", "P-08", "P-09"]:
            assert rules_by_id[pid]["principal"] == "Owner", f"{pid} should have Owner principal"

        # System rules
        for pid in ["P-03", "P-04", "P-07"]:
            assert rules_by_id[pid]["principal"] == "System", f"{pid} should have System principal"

        # P-05 has mixed principal (Owner or System)
        assert rules_by_id["P-05"]["principal"] == "any", "P-05 should have 'any' principal (mixed)"

    def test_parse_cedar_policies_actions(self):
        """Check that actions are correctly extracted."""
        rules = _parse_cedar_policies()
        rules_by_id = {r["id"]: r for r in rules}

        assert rules_by_id["P-01"]["action"] == "approve"
        assert rules_by_id["P-03"]["action"] == "hold"
        assert rules_by_id["P-04"]["action"] == "fast_pay"
        assert rules_by_id["P-05"]["action"] == "settle"
        assert rules_by_id["P-06"]["action"] == "change_bank_details"
        # P-02 and P-07 have action lists
        assert "hold" in rules_by_id["P-02"]["action"]
        assert "read" in rules_by_id["P-07"]["action"]

    def test_parse_cedar_policies_resources(self):
        """All rules should have Payment as resource."""
        rules = _parse_cedar_policies()
        for rule in rules:
            assert rule["resource"] == "Payment", f"Rule {rule['id']} has resource {rule['resource']}"


class TestTrustAPI:
    """Tests for the /v1/trust endpoint."""

    def test_trust_endpoint_returns_200(self, client):
        response = client.get("/v1/trust")
        assert response.status_code == 200

    def test_trust_endpoint_returns_structure(self, client):
        response = client.get("/v1/trust")
        assert response.status_code == 200
        data = response.json()

        assert "generated_at" in data
        assert "version" in data
        assert "security_controls" in data
        assert "data_handling" in data
        assert "infrastructure" in data
        assert "not_yet_implemented" in data

    def test_trust_security_controls_structure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        sc = data["security_controls"]
        assert "policy_engine" in sc
        assert "owner_approval_required" in sc
        assert "model_restrictions" in sc
        assert "kickback_email_controls" in sc
        assert "prompt_injection_defenses" in sc
        assert "redteam_suite" in sc
        assert "sender_verification" in sc
        assert "pydantic_validation" in sc
        assert "policy_hold_reasons" in sc

    def test_trust_policy_engine(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        pe = data["security_controls"]["policy_engine"]
        assert pe["type"] == "Cedar (default-deny)"
        assert "description" in pe
        assert "total_rules" in pe
        assert isinstance(pe["rules"], list)
        assert pe["total_rules"] >= 0

    def test_trust_cedar_rules_structure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        rules = data["security_controls"]["policy_engine"]["rules"]
        if rules:
            rule = rules[0]
            assert "id" in rule
            assert "type" in rule
            assert rule["type"] in ["permit", "forbid"]
            assert "principal" in rule

    def test_trust_model_restrictions(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        mr = data["security_controls"]["model_restrictions"]
        assert "description" in mr
        assert "permitted_actions" in mr
        assert "forbidden_actions" in mr
        assert "read" in mr["permitted_actions"]
        assert "explain" in mr["permitted_actions"]
        assert "approve" in mr["forbidden_actions"]
        assert "settle" in mr["forbidden_actions"]
        assert "fast_pay" in mr["forbidden_actions"]

    def test_trust_sender_verification(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        sv = data["security_controls"]["sender_verification"]
        assert "description" in sv
        assert "checks" in sv
        assert isinstance(sv["checks"], list)
        assert len(sv["checks"]) >= 5

        check_names = [c["check"] for c in sv["checks"]]
        assert "SPF verification" in check_names
        assert "DKIM verification" in check_names
        assert "DMARC verification" in check_names
        assert "Lookalike domain detection" in check_names

    def test_trust_redteam_suite(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        rt = data["security_controls"]["redteam_suite"]
        assert "description" in rt
        assert "total_cases" in rt
        assert "categories" in rt
        assert "endpoint" in rt
        assert rt["total_cases"] >= 15
        assert rt["endpoint"] == "GET /v1/redteam"

    def test_trust_pydantic_validation(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        pv = data["security_controls"]["pydantic_validation"]
        assert "description" in pv
        assert "validation_on" in pv
        assert isinstance(pv["validation_on"], list)
        assert len(pv["validation_on"]) >= 3

    def test_trust_policy_hold_reasons(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        phr = data["security_controls"]["policy_hold_reasons"]
        assert "description" in phr
        assert "reasons" in phr
        assert isinstance(phr["reasons"], list)
        assert len(phr["reasons"]) >= 5

        if phr["reasons"]:
            reason = phr["reasons"][0]
            assert "reason" in reason
            assert "resolution" in reason

    def test_trust_data_handling_structure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        dh = data["data_handling"]
        assert "storage" in dh
        assert "network_isolation" in dh
        assert "llm_data_handling" in dh
        assert "demo_data" in dh

    def test_trust_storage(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        storage = data["data_handling"]["storage"]
        assert "database" in storage
        assert "object_storage" in storage

        db = storage["database"]
        assert "type" in db
        assert "location" in db
        assert "description" in db

    def test_trust_network_isolation(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        ni = data["data_handling"]["network_isolation"]
        assert "vpc_private" in ni
        assert "firewall" in ni

        fw = ni["firewall"]
        assert "default_deny_inbound" in fw
        assert "allowed_inbound" in fw
        assert fw["default_deny_inbound"] is True

    def test_trust_llm_data_handling(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        llm = data["data_handling"]["llm_data_handling"]
        assert "deterministic_path" in llm
        assert "hosted_inference" in llm

        dp = llm["deterministic_path"]
        assert "description" in dp
        assert "decider_active" in dp
        assert "llm_mode" in dp

    def test_trust_infrastructure_structure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        infra = data["infrastructure"]
        assert "deployment" in infra
        assert "settlement" in infra
        assert "model" in infra

    def test_trust_deployment(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        deployment = data["infrastructure"]["deployment"]
        assert "provider" in deployment
        assert "region" in deployment
        assert "products" in deployment
        assert isinstance(deployment["products"], list)
        assert len(deployment["products"]) >= 3

    def test_trust_not_yet_implemented(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        nyi = data["not_yet_implemented"]
        assert "description" in nyi
        assert "items" in nyi
        assert isinstance(nyi["items"], list)
        assert len(nyi["items"]) >= 3

        if nyi["items"]:
            item = nyi["items"][0]
            assert "item" in item
            assert "status" in item
            assert "description" in item

    def test_trust_honest_soc2_disclosure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        items = data["not_yet_implemented"]["items"]
        soc2_items = [i for i in items if "SOC 2" in i["item"]]
        assert len(soc2_items) >= 1
        assert soc2_items[0]["status"] in ["not_started", "not_implemented"]

    def test_trust_honest_pentest_disclosure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        items = data["not_yet_implemented"]["items"]
        pentest_items = [i for i in items if "penetration" in i["item"].lower()]
        assert len(pentest_items) >= 1
        assert pentest_items[0]["status"] in ["not_started", "not_implemented"]

    def test_trust_honest_testnet_disclosure(self, client):
        response = client.get("/v1/trust")
        data = response.json()

        items = data["not_yet_implemented"]["items"]
        testnet_items = [
            i for i in items if "settlement" in i["item"].lower() or "testnet" in i["description"].lower()
        ]
        assert len(testnet_items) >= 1
