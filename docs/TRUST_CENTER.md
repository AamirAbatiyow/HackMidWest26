# Vouch Trust Center

The Trust Center provides transparent, verifiable information about Vouch's security controls, data handling practices, infrastructure, and honest disclosure of what is not yet implemented.

## Overview

Vouch is a deterministic-safeguard payables/invoice-fraud tool designed for business owners. It combines:

- **Strands agents** for intelligent document processing
- **Cedar default-deny policies** for authorization
- **PyTorch/LIME model** for fraud risk scoring with explainable AI
- **XRPL testnet settlement** for payment execution
- **Akamai deployment** for infrastructure

## Accessing the Trust Center

### API Endpoint

```
GET /v1/trust
```

Returns a structured JSON response with all trust-related information.

### Frontend

Navigate to `/trust` in the Vouch frontend to view the Trust Center page.

## Security Controls

### Cedar Policy Engine (Default-Deny)

All actions in Vouch are denied unless explicitly permitted by a Cedar policy rule. The policy file is located at `backend/projects/vouch/policies/vouch.cedar`.

Key rules include:

| Rule ID | Principal | Action | Description |
|---------|-----------|--------|-------------|
| P-01 | Owner | approve | Owner may approve a payment that is pending, held, or appealed |
| P-02 | Owner | hold, appeal | Owner may hold or appeal any unsettled payment |
| P-03 | System | hold | Automated system may place a hold, never a denial |
| P-04 | System | fast_pay | Fast pay for vouched, eligible payments within limits |
| P-05 | Owner/System | settle | Settlement requires recorded owner approval |
| P-06 | Owner | change_bank_details | Bank change only after callback verification |
| P-07 | System | read, explain | System may read and explain; explanations never carry authority |
| P-08 | Owner | approve_kickback, decline_kickback | Owner approves kickback email draft |
| P-09 | Owner | send_kickback | Owner sends approved kickback once |

### Model Restrictions

The ML model has **NO permit** to:
- Approve payments
- Settle payments
- Fast-pay
- Deny vendors
- Modify amounts
- Change bank details

The model can only **read** and **explain**. Explanations never carry authority.

### Sender Verification

Before any LLM processes an invoice, deterministic sender checks run:

1. **SPF verification** - Validates Sender Policy Framework records
2. **DKIM verification** - Validates DomainKeys Identified Mail signatures
3. **DMARC verification** - Validates Domain-based Message Authentication
4. **Lookalike domain detection** - Detects typosquatting and homoglyph attacks
5. **Reply-to mismatch** - Flags when reply-to differs from sender domain
6. **Display name mismatch** - Flags when display name suggests a known vendor but domain differs
7. **Freemail sender** - Flags invoices from gmail.com, outlook.com, etc.
8. **New sender for known vendor** - Flags when a known vendor sends from unregistered domain

### Prompt Injection Defenses

The deterministic kernel checks invoice text for instructions aimed at the payment system before any LLM processing. Any detected injection places the card on hold with reason `R_INJECTION`.

### Red-team Suite

Vouch includes an adversarial test suite with 31+ test cases covering:
- Prompt injection attacks
- Malicious LLM outputs
- Approval manipulation
- Limit bypasses
- Identity attacks
- Policy violations

All attacks must be blocked for the suite to pass. Results are available at `GET /v1/redteam`.

### Strict Schema Validation

All classifier outputs are validated against strict Pydantic schemas:
- `FormatDecision`
- `ToolDecision`
- `IntakeExtraction`
- `Explanations`
- `InvestigationReport`

Malformed or extra fields are rejected.

### Policy Hold Reasons

Every hold has a documented reason and resolution path. Vendors are never auto-denied.

| Reason | Resolution |
|--------|------------|
| Unresolved high fraud risk | Owner reviews evidence and resolves with a note |
| Bank details changed without confirmation | Confirm by calling vendor at phone on file |
| Amount exceeds single-payment limit | Owner approves a one-time limit override |
| Amount not verified by deterministic kernel | Re-key the amount from source document |
| Possible duplicate invoice | Owner confirms this is not a duplicate |
| Vendor not on master file | Onboard the vendor before paying |
| Invoice email failed sender checks | Confirm with vendor through channel on file |
| Prompt injection detected | Owner reviews; vendor re-sends clean invoice |

## Data Handling

### Storage

| Component | Type | Location | Purpose |
|-----------|------|----------|---------|
| Database | PostgreSQL | us-ord (Chicago) | Audit trail and policy records for every decision |
| Object Storage | Akamai Object Storage | us-ord-1 | Invoice attachments and supporting documents |

### Network Isolation

- **Model Server**: Runs in VPC-private subnet (10.0.3.0/24)
- **Decider Server**: Runs in VPC-private subnet
- **Database**: Accessible only from app tier (10.0.4.0/24)

### Cloud Firewall

- Default deny inbound
- Allowed inbound: 443/TCP (HTTPS), 80/TCP (redirect)
- Explicit allow-list for outbound connections

### LLM Data Handling

When the Decider/deterministic path is used, **no invoice data is sent to third-party LLM**.

When LLM is used, it is Akamai-hosted inference (Akamai Cloud Inference at `https://ws.akamai-workshops.com/v1`), not OpenAI/Anthropic directly.

### Demo Data

All demo/test data is synthetic. No real customer data is used in demos.

## Infrastructure

### Deployment

| Attribute | Value |
|-----------|-------|
| Provider | Akamai Cloud Computing (Linode) |
| Region | us-ord (Chicago) |

### Akamai Products Used

- Dedicated-CPU Linode
- Akamai VPC
- Akamai Cloud Firewall
- Akamai NodeBalancer
- Akamai Managed Database (PostgreSQL)
- Akamai Object Storage
- Akamai Cloud Inference

### Settlement

- Adapter: XRPL
- Network: XRPL Testnet
- Note: **Testnet only - no real money movement**

### Model

- Name: vouch-risk
- Type: PyTorch fraud detection model
- Explainability: LIME explanations

## What is NOT Yet Implemented

Honest disclosure of what Vouch does NOT have yet:

| Item | Status | Description |
|------|--------|-------------|
| SOC 2 certification | Not started | No SOC 2 Type I or Type II audit has been performed |
| Third-party penetration test | Not started | No external pen test; only internal red-team suite |
| Production settlement | Testnet only | Settlement is on XRPL Testnet only; no real money movement |
| Intake shared secret validation | Not implemented | Intake endpoint does not validate shared secret from email forwarders |
| Multi-tenant isolation | Not implemented | Single-tenant deployment only; no multi-org isolation |
| Encryption at rest | Provider managed | Relies on provider-level encryption; no customer-managed keys |

## API Response Structure

The `/v1/trust` endpoint returns:

```json
{
  "generated_at": "ISO timestamp",
  "version": "0.1.0",
  "security_controls": {
    "policy_engine": { ... },
    "owner_approval_required": { ... },
    "model_restrictions": { ... },
    "kickback_email_controls": { ... },
    "prompt_injection_defenses": { ... },
    "redteam_suite": { ... },
    "sender_verification": { ... },
    "pydantic_validation": { ... },
    "policy_hold_reasons": { ... }
  },
  "data_handling": {
    "storage": { ... },
    "network_isolation": { ... },
    "llm_data_handling": { ... },
    "demo_data": { ... }
  },
  "infrastructure": {
    "deployment": { ... },
    "settlement": { ... },
    "model": { ... }
  },
  "not_yet_implemented": {
    "description": "...",
    "items": [ ... ]
  }
}
```

## Verification

All data in the Trust Center is derived from the real codebase and configuration:

- Cedar rules are parsed from `vouch.cedar`
- Red-team case count comes from `redteam.py`
- Hold reasons come from `policy/release.py`
- Sender checks come from `sender/check.py`
- Infrastructure details come from runtime settings

No certifications or claims are invented. Only verifiable facts are stated.
