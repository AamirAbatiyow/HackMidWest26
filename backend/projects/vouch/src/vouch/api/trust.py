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


def _get_redteam_info() -> dict[str, Any]:
    """Get red-team suite info, using cached results if available."""
    try:
        from ..redteam import CASES

        svc = get_service()
        if svc.redteam is not None:
            # Use cached results
            results = svc.redteam
            return {
                "total": results["total"],
                "blocked": results["blocked"],
                "all_blocked": results["all_blocked"],
                "ran_at": results.get("ran_at"),
            }
        # No cached results yet, just return count from CASES
        return {"total": len(CASES), "blocked": None, "all_blocked": None, "ran_at": None}
    except Exception:
        return {"total": 0, "blocked": None, "all_blocked": None, "ran_at": None}


def _parse_cedar_policies() -> list[dict[str, Any]]:
    """Parse Cedar policy file and extract rule IDs, actions, principals, and descriptions.

    Handles rules with when/unless clauses by tracking brace depth to find rule boundaries.
    Extracts only the immediately preceding comment block as each rule's description.
    """
    import re

    policy_file = POLICY_DIR / "vouch.cedar"
    if not policy_file.exists():
        return []

    content = policy_file.read_text()
    lines = content.split("\n")
    rules: list[dict[str, Any]] = []

    # Find all @id annotations and their line indices
    id_pattern = re.compile(r'@id\("([^"]+)"\)')

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        id_match = id_pattern.match(stripped)
        if not id_match:
            i += 1
            continue

        rule_id = id_match.group(1)

        # Extract the description from the immediately preceding comment block only
        # Walk backwards to find consecutive comment lines, stopping at blank or non-comment
        description_lines: list[str] = []
        j = i - 1
        while j >= 0:
            prev = lines[j].strip()
            if prev.startswith("//"):
                # Only include this comment if the line before it is also a comment or @id
                # This prevents grabbing the file header for P-03 which follows a blank line
                comment_text = prev[2:].strip()
                # Check if this is part of the same block
                if j == i - 1 or (j > 0 and lines[j + 1].strip().startswith("//")):
                    description_lines.insert(0, comment_text)
                    j -= 1
                else:
                    break
            elif prev == "":
                # Empty line breaks the comment block
                break
            else:
                break
        description = " ".join(description_lines) if description_lines else None

        # Move to permit/forbid line
        i += 1
        if i >= len(lines):
            break

        effect_line = lines[i].strip()
        if effect_line.startswith("permit("):
            effect = "permit"
        elif effect_line.startswith("forbid("):
            effect = "forbid"
        else:
            continue

        # Now parse the rule body by tracking brace/paren depth
        # A rule ends when we see `;` at depth 0 (after closing the main block and any when/unless)
        rule_text_lines = []
        brace_depth = 0
        paren_depth = 0
        rule_complete = False

        while i < len(lines) and not rule_complete:
            line = lines[i]
            rule_text_lines.append(line)

            for ch in line:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                elif ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
                elif ch == ";" and paren_depth == 0 and brace_depth == 0:
                    rule_complete = True
                    break
            i += 1

        rule_text = "\n".join(rule_text_lines)

        # Extract principal from the permit/forbid clause, NOT from the when clause
        # The principal is between "permit(" or "forbid(" and the first ")".
        # We look for "principal is X" only in the initial clause, not in when { ... }
        principal = "any"
        # Find the permit/forbid clause (before any when { })
        clause_end = rule_text.find(") when")
        if clause_end == -1:
            clause_end = rule_text.find(");")
        if clause_end == -1:
            clause_end = len(rule_text)
        clause_text = rule_text[:clause_end]

        if "principal is Owner" in clause_text:
            principal = "Owner"
        elif "principal is System" in clause_text:
            principal = "System"
        elif "principal is Model" in clause_text:
            principal = "Model"

        # Extract action(s)
        action: str | None = None
        action_single = re.search(r'action\s*==\s*Action::"([^"]+)"', rule_text)
        action_list = re.search(r"action\s+in\s+\[([^\]]+)\]", rule_text)
        if action_single:
            action = action_single.group(1)
        elif action_list:
            action_items = re.findall(r'Action::"([^"]+)"', action_list.group(1))
            action = ", ".join(action_items) if action_items else None

        # Extract resource
        resource: str | None = None
        resource_match = re.search(r"resource\s+is\s+(\w+)", rule_text)
        if resource_match:
            resource = resource_match.group(1)

        rules.append(
            {
                "id": rule_id,
                "type": effect,
                "principal": principal,
                "action": action,
                "resource": resource,
                "description": description,
            }
        )

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


def _get_scorer_info(settings: Any) -> dict[str, str]:
    """Get accurate description of the scorer configuration."""
    svc = get_service()
    scorer = svc.engine.scorer()
    scorer_name = getattr(scorer, "name", settings.scorer)

    if scorer_name == "inference-service":
        return {
            "scorer": scorer_name,
            "description": f"Inference service at {settings.model_server_url or settings.inference_url}",
            "model_server_claim": "Model inference server runs in VPC-private subnet (10.0.3.0/24)",
        }
    elif scorer_name == "local-torch":
        return {
            "scorer": scorer_name,
            "description": "PyTorch fraud detection model running in-process with LIME explanations",
            "model_server_claim": "Scorer runs in-process (local-torch); no separate model server",
        }
    else:
        return {
            "scorer": scorer_name,
            "description": "Heuristic fallback scorer (no model loaded)",
            "model_server_claim": "Using heuristic fallback; no model server configured",
        }


def _get_database_info(settings: Any) -> dict[str, str]:
    """Get accurate database type based on actual configuration."""
    if settings.is_postgres:
        return {
            "type": "PostgreSQL",
            "description": "Audit trail and policy records for every decision",
            "vpc_claim": "PostgreSQL accessible only from app tier (10.0.4.0/24)",
        }
    else:
        return {
            "type": "SQLite (local dev)",
            "description": "Local SQLite database for development",
            "vpc_claim": "SQLite local file (no network access needed)",
        }


@router.get("/trust")
def get_trust() -> dict[str, Any]:
    """Return the Trust Center data: security controls, data handling, infrastructure, and limitations.

    All data is derived from the real codebase and configuration, not invented.
    """
    settings = get_settings()
    get_service()  # ensure service is initialized

    cedar_rules = _parse_cedar_policies()
    redteam_info = _get_redteam_info()
    hold_reasons = _get_policy_hold_reasons()
    sender_checks = _get_sender_checks()
    scorer_info = _get_scorer_info(settings)
    db_info = _get_database_info(settings)

    owner_actions = [r for r in cedar_rules if r.get("principal") == "Owner" and r.get("type") == "permit"]
    model_permits = [r for r in cedar_rules if r.get("principal") == "Model"]

    # Build truthful redteam description based on actual results
    if redteam_info["blocked"] is not None:
        blocked_count = redteam_info["blocked"]
        total_count = redteam_info["total"]
        if redteam_info["all_blocked"]:
            redteam_desc = f"Adversarial test suite: {blocked_count}/{total_count} attacks blocked."
        else:
            redteam_desc = (
                f"Adversarial test suite: {blocked_count}/{total_count} attacks blocked (SOME FAILURES)."
            )
    else:
        redteam_desc = (
            f"Adversarial test suite with {redteam_info['total']} cases (not yet run this session)."
        )

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
                "hold_reason": "R_INJECTION: the invoice text tries to give orders to the payment system",
            },
            "redteam_suite": {
                "description": redteam_desc,
                "total_cases": redteam_info["total"],
                "blocked_cases": redteam_info["blocked"],
                "all_blocked": redteam_info["all_blocked"],
                "ran_at": redteam_info["ran_at"],
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
                    "type": db_info["type"],
                    "location": settings.region,
                    "description": db_info["description"],
                },
                "object_storage": {
                    "configured": settings.has_bucket,
                    "region": settings.obj_region,
                    "description": "Invoice attachments and supporting documents",
                },
            },
            "network_isolation": {
                "vpc_private": {
                    "model_server": scorer_info["model_server_claim"],
                    "decider_server": "Strands Decider server runs in VPC-private subnet"
                    if settings.decider_active
                    else "Decider not active; deterministic routing only",
                    "database": db_info["vpc_claim"],
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
                "products": _get_actual_products(settings, db_info),
            },
            "settlement": {
                "adapter": settings.settlement_adapter,
                "network": "XRPL Testnet" if settings.settlement_adapter == "xrpl" else "Mock (demo)",
                "description": "Settlement adapter for payment execution",
            },
            "model": {
                "name": settings.model_name,
                "scorer": scorer_info["scorer"],
                "description": scorer_info["description"],
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


def _get_actual_products(settings: Any, db_info: dict[str, str]) -> list[str]:
    """Return the list of Akamai products actually in use based on config."""
    products = ["Dedicated-CPU Linode", "Akamai VPC", "Akamai Cloud Firewall", "Akamai NodeBalancer"]
    if db_info["type"] == "PostgreSQL":
        products.append("Akamai Managed Database (PostgreSQL)")
    if settings.has_bucket:
        products.append("Akamai Object Storage")
    if settings.has_llm_key:
        products.append("Akamai Cloud Inference")
    return products
