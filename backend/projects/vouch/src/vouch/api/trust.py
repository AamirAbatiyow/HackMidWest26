"""GET /v1/trust: Trust Center endpoint returning structured security posture data.

Provides real, verifiable information about Vouch's security controls, data handling,
infrastructure, and honest disclosure of what is NOT yet implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from ..config import POLICY_DIR, get_settings
from .state import get_service

router = APIRouter(prefix="/v1", tags=["trust"])


def _count_redteam_cases() -> int:
    """Count red-team attack cases from the CASES list in redteam.py."""
    try:
        from ..redteam import CASES

        return len(CASES)
    except Exception:
        return 0


def _parse_cedar_policies() -> list[dict[str, Any]]:
    """Parse Cedar policy file and extract rule IDs, actions, and principals."""
    policy_file = POLICY_DIR / "vouch.cedar"
    if not policy_file.exists():
        return []

    rules: list[dict[str, Any]] = []
    content = policy_file.read_text()

    current_id = None
    current_description = None
    in_permit = False
    in_forbid = False
    principal = None
    action = None
    resource = None

    for line in content.split("\n"):
        stripped = line.strip()

        if stripped.startswith("@id("):
            current_id = stripped.split('"')[1] if '"' in stripped else None
        elif stripped.startswith("//") and current_id is None:
            if current_description is None:
                current_description = stripped[2:].strip()
            else:
                current_description += " " + stripped[2:].strip()
        elif stripped.startswith("permit("):
            in_permit = True
            in_forbid = False
        elif stripped.startswith("forbid("):
            in_forbid = True
            in_permit = False
        elif (in_permit or in_forbid) and "principal" in stripped:
            if "is Owner" in stripped:
                principal = "Owner"
            elif "is System" in stripped:
                principal = "System"
            elif "is Model" in stripped:
                principal = "Model"
            else:
                principal = "any"
        elif (in_permit or in_forbid) and "action" in stripped:
            if "==" in stripped:
                action = stripped.split('"')[1] if '"' in stripped else None
            elif "in [" in stripped:
                actions = []
                for part in stripped.split('"'):
                    if (
                        part
                        and not part.startswith("action")
                        and "::" not in part
                        and part.strip()
                        and part.strip() not in [",", "[", "]", "in"]
                    ):
                        actions.append(part)
                action = ", ".join(actions) if actions else None
        elif (in_permit or in_forbid) and "resource is" in stripped:
            resource = stripped.split("is")[-1].strip().rstrip(";")
        elif stripped.startswith(");") and (in_permit or in_forbid):
            if current_id:
                rules.append(
                    {
                        "id": current_id,
                        "type": "permit" if in_permit else "forbid",
                        "principal": principal or "any",
                        "action": action,
                        "resource": resource,
                        "description": current_description,
                    }
                )
            in_permit = False
            in_forbid = False
            current_id = None
            current_description = None
            principal = None
            action = None
            resource = None

    return rules


def _get_policy_hold_reasons() -> list[dict[str, str]]:
    """Get the policy hold reasons and their required actions from release.py."""
    from ..policy.release import REQUIRED_ACTIONS

    return [{"reason": reason, "resolution": action} for reason, action in REQUIRED_ACTIONS.items()]


def _get_sender_checks() -> list[dict[str, str]]:
    """Describe the deterministic sender checks from sender/check.py."""
    return [
        {
            "check": "SPF verification",
            "description": "Validates Sender Policy Framework records (fail, softfail, permerror flagged)",
        },
        {
            "check": "DKIM verification",
            "description": "Validates DomainKeys Identified Mail signatures (fail, permerror, missing flagged)",
        },
        {
            "check": "DMARC verification",
            "description": "Validates Domain-based Message Authentication (fail flagged)",
        },
        {
            "check": "Lookalike domain detection",
            "description": "Detects typosquatting and homoglyph attacks against known vendor domains",
        },
        {
            "check": "Reply-to mismatch",
            "description": "Flags when reply-to address differs from sender domain",
        },
        {
            "check": "Display name mismatch",
            "description": "Flags when display name suggests a known vendor but domain differs",
        },
        {
            "check": "Freemail sender",
            "description": "Flags invoices from gmail.com, outlook.com, etc. for known business vendors",
        },
        {
            "check": "New sender for known vendor",
            "description": "Flags when a known vendor sends from an unregistered email domain",
        },
    ]


@router.get("/trust")
def get_trust() -> dict[str, Any]:
    """Return the Trust Center data: security controls, data handling, infrastructure, and limitations.

    All data is derived from the real codebase and configuration, not invented.
    """
    settings = get_settings()
    get_service()  # ensure service is initialized

    cedar_rules = _parse_cedar_policies()
    redteam_count = _count_redteam_cases()
    hold_reasons = _get_policy_hold_reasons()
    sender_checks = _get_sender_checks()

    owner_actions = [r for r in cedar_rules if r.get("principal") == "Owner" and r.get("type") == "permit"]
    model_permits = [r for r in cedar_rules if r.get("principal") == "Model"]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "version": settings.version,
        "security_controls": {
            "policy_engine": {
                "type": "Cedar (default-deny)",
                "description": "All actions are denied unless explicitly permitted by a Cedar policy rule.",
                "total_rules": len(cedar_rules),
                "rules": cedar_rules,
            },
            "owner_approval_required": {
                "description": "Money movement requires explicit owner approval; no automated payments.",
                "owner_permitted_actions": [
                    {
                        "rule_id": r["id"],
                        "action": r.get("action"),
                        "description": r.get("description"),
                    }
                    for r in owner_actions
                ],
            },
            "model_restrictions": {
                "description": "The ML model has NO permit to approve, settle, fast-pay, deny vendors, or modify amounts. It can only read and explain.",
                "model_rules": model_permits,
                "permitted_actions": ["read", "explain"],
                "forbidden_actions": [
                    "approve",
                    "settle",
                    "fast_pay",
                    "deny_vendor",
                    "modify_amount",
                    "change_bank_details",
                ],
            },
            "kickback_email_controls": {
                "description": "Kickback emails (requests to vendors for readable invoices) require owner approval before sending.",
                "rules": ["P-08: Owner approves/declines kickback", "P-09: Owner sends approved kickback"],
            },
            "prompt_injection_defenses": {
                "description": "Deterministic kernel checks invoice text for instructions aimed at the payment system before any LLM processing.",
                "hold_reason": "R_INJECTION: invoice text contains instructions aimed at the payment system",
            },
            "redteam_suite": {
                "description": "Adversarial test suite run on every deployment; all attacks must be blocked.",
                "total_cases": redteam_count,
                "categories": [
                    "injection",
                    "llm_output",
                    "approval",
                    "limits",
                    "identity",
                    "policy",
                ],
                "endpoint": "GET /v1/redteam",
            },
            "sender_verification": {
                "description": "Deterministic sender checks run before any LLM reads the invoice.",
                "checks": sender_checks,
            },
            "pydantic_validation": {
                "description": "All classifier outputs are validated against strict Pydantic schemas; malformed or extra fields are rejected.",
                "validation_on": [
                    "FormatDecision",
                    "ToolDecision",
                    "IntakeExtraction",
                    "Explanations",
                    "InvestigationReport",
                ],
            },
            "policy_hold_reasons": {
                "description": "Every hold has a documented reason and resolution path; vendors are never auto-denied.",
                "reasons": hold_reasons,
            },
        },
        "data_handling": {
            "storage": {
                "database": {
                    "type": "PostgreSQL" if settings.is_postgres else "SQLite (local dev)",
                    "location": settings.region,
                    "description": "Audit trail and policy records for every decision",
                },
                "object_storage": {
                    "configured": settings.has_bucket,
                    "region": settings.obj_region,
                    "description": "Invoice attachments and supporting documents",
                },
            },
            "network_isolation": {
                "vpc_private": {
                    "model_server": "Model inference server runs in VPC-private subnet (10.0.3.0/24)",
                    "decider_server": "Strands Decider server runs in VPC-private subnet",
                    "database": "PostgreSQL accessible only from app tier (10.0.4.0/24)",
                },
                "firewall": {
                    "default_deny_inbound": True,
                    "allowed_inbound": ["443/TCP (HTTPS)", "80/TCP (redirect)"],
                    "description": "Cloud Firewall with explicit allow-list",
                },
            },
            "llm_data_handling": {
                "deterministic_path": {
                    "description": "When Decider/deterministic path is used, no invoice data is sent to third-party LLM.",
                    "decider_active": settings.decider_active,
                    "llm_mode": settings.effective_llm_mode,
                },
                "hosted_inference": {
                    "provider": "Akamai Cloud Inference",
                    "base_url": settings.akamai_base_url,
                    "description": "When LLM is used, it is Akamai-hosted inference (not OpenAI/Anthropic directly).",
                },
            },
            "demo_data": {
                "description": "All demo/test data is synthetic; no real customer data in demos.",
                "synthetic_vendors": True,
                "synthetic_invoices": True,
            },
        },
        "infrastructure": {
            "deployment": {
                "provider": "Akamai Cloud Computing (Linode)",
                "region": settings.region,
                "products": [
                    "Dedicated-CPU Linode",
                    "Akamai VPC",
                    "Akamai Cloud Firewall",
                    "Akamai NodeBalancer",
                    "Akamai Managed Database (PostgreSQL)",
                    "Akamai Object Storage",
                    "Akamai Cloud Inference",
                ],
            },
            "settlement": {
                "adapter": settings.settlement_adapter,
                "network": "XRPL Testnet" if settings.settlement_adapter == "xrpl" else "Mock (demo)",
                "description": "Settlement adapter for payment execution",
            },
            "model": {
                "name": settings.model_name,
                "scorer": settings.scorer,
                "description": "PyTorch fraud detection model with LIME explanations",
            },
        },
        "not_yet_implemented": {
            "description": "Honest disclosure of what Vouch does NOT have yet.",
            "items": [
                {
                    "item": "SOC 2 certification",
                    "status": "not_started",
                    "description": "No SOC 2 Type I or Type II audit has been performed.",
                },
                {
                    "item": "Third-party penetration test",
                    "status": "not_started",
                    "description": "No external pen test has been conducted; only internal red-team suite.",
                },
                {
                    "item": "Production settlement",
                    "status": "testnet_only",
                    "description": "Settlement is on XRPL Testnet only; no real money movement.",
                },
                {
                    "item": "Intake shared secret validation",
                    "status": "not_implemented",
                    "description": "Intake endpoint does not yet validate a shared secret from email forwarders.",
                },
                {
                    "item": "Multi-tenant isolation",
                    "status": "not_implemented",
                    "description": "Single-tenant deployment only; no multi-org isolation.",
                },
                {
                    "item": "Encryption at rest",
                    "status": "provider_managed",
                    "description": "Relies on Akamai/Linode provider-level encryption; no customer-managed keys.",
                },
            ],
        },
    }
