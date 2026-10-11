import type { TrustData } from '@/api/types'

export const DEMO_TRUST: TrustData = {
  generated_at: new Date().toISOString(),
  version: '0.1.0',
  security_controls: {
    policy_engine: {
      type: 'Cedar (default-deny)',
      description: 'All actions are denied unless explicitly permitted by a Cedar policy rule.',
      total_rules: 9,
      rules: [
        { id: 'P-01', type: 'permit', principal: 'Owner', action: 'approve', resource: 'Payment', description: 'Owner may approve a payment pending/held/appealed' },
        { id: 'P-02', type: 'permit', principal: 'Owner', action: 'hold, appeal', resource: 'Payment', description: 'Owner may hold or appeal any unsettled payment' },
        { id: 'P-03', type: 'permit', principal: 'System', action: 'hold', resource: 'Payment', description: 'Automated system may place a hold, never a denial' },
        { id: 'P-04', type: 'permit', principal: 'System', action: 'fast_pay', resource: 'Payment', description: 'Fast pay for vouched, eligible payments within limits' },
        { id: 'P-05', type: 'permit', principal: 'any', action: 'settle', resource: 'Payment', description: 'Settlement requires recorded owner approval' },
        { id: 'P-06', type: 'permit', principal: 'Owner', action: 'change_bank_details', resource: 'Payment', description: 'Bank change only after callback verification' },
        { id: 'P-07', type: 'permit', principal: 'System', action: 'read, explain', resource: 'Payment', description: 'System may read and explain; explanations never carry authority' },
        { id: 'P-08', type: 'permit', principal: 'Owner', action: 'approve_kickback, decline_kickback', resource: 'Payment', description: 'Owner approves kickback email draft' },
        { id: 'P-09', type: 'permit', principal: 'Owner', action: 'send_kickback', resource: 'Payment', description: 'Owner sends approved kickback once' },
      ],
    },
    owner_approval_required: {
      description: 'Money movement requires explicit owner approval; no automated payments.',
      owner_permitted_actions: [
        { rule_id: 'P-01', action: 'approve', description: 'Owner may approve a payment' },
        { rule_id: 'P-05', action: 'settle', description: 'Owner settles approved payments' },
        { rule_id: 'P-06', action: 'change_bank_details', description: 'Owner confirms bank changes' },
      ],
    },
    model_restrictions: {
      description: 'The ML model has NO permit to approve, settle, fast-pay, deny vendors, or modify amounts. It can only read and explain.',
      model_rules: [],
      permitted_actions: ['read', 'explain'],
      forbidden_actions: ['approve', 'settle', 'fast_pay', 'deny_vendor', 'modify_amount', 'change_bank_details'],
    },
    kickback_email_controls: {
      description: 'Kickback emails require owner approval before sending.',
      rules: ['P-08: Owner approves/declines kickback', 'P-09: Owner sends approved kickback'],
    },
    prompt_injection_defenses: {
      description: 'Deterministic kernel checks invoice text for instructions aimed at the payment system.',
      hold_reason: 'R_INJECTION: the invoice text tries to give orders to the payment system',
    },
    redteam_suite: {
      description: 'Adversarial test suite: 31/31 attacks blocked.',
      total_cases: 31,
      blocked_cases: 31,
      all_blocked: true,
      ran_at: new Date().toISOString().slice(0, 10),
      categories: ['injection', 'llm_output', 'approval', 'limits', 'identity', 'policy'],
      endpoint: 'GET /v1/redteam',
    },
    sender_verification: {
      description: 'Deterministic sender checks run before any LLM reads the invoice.',
      checks: [
        { check: 'SPF verification', description: 'Validates Sender Policy Framework records' },
        { check: 'DKIM verification', description: 'Validates DomainKeys Identified Mail signatures' },
        { check: 'DMARC verification', description: 'Validates Domain-based Message Authentication' },
        { check: 'Lookalike domain detection', description: 'Detects typosquatting and homoglyph attacks' },
        { check: 'Reply-to mismatch', description: 'Flags when reply-to differs from sender domain' },
        { check: 'Display name mismatch', description: 'Flags when display name suggests a known vendor but domain differs' },
        { check: 'Freemail sender', description: 'Flags invoices from gmail.com, outlook.com, etc.' },
        { check: 'New sender for known vendor', description: 'Flags when a known vendor sends from unregistered domain' },
      ],
    },
    pydantic_validation: {
      description: 'All classifier outputs validated against strict Pydantic schemas.',
      validation_on: ['FormatDecision', 'ToolDecision', 'IntakeExtraction', 'Explanations', 'InvestigationReport'],
    },
    policy_hold_reasons: {
      description: 'Every hold has a documented reason and resolution path.',
      reasons: [
        { reason: 'the fraud risk score is high', resolution: 'review the evidence and clear it with a note' },
        { reason: 'the bank account changed and nobody has confirmed it by phone', resolution: 'confirm the new bank account by calling the vendor on a number you already have' },
        { reason: 'the amount is over your single-payment limit', resolution: 'approve a one-time limit override' },
        { reason: 'the amount could not be read from the invoice', resolution: 'type in the amount from the original invoice' },
        { reason: 'this looks like a duplicate invoice', resolution: 'confirm this is not a double payment' },
        { reason: 'this vendor is not in your vendor list', resolution: 'add the vendor to your list after checking their identity and bank account' },
        { reason: "the email did not come from the vendor's usual address", resolution: 'confirm the invoice with the vendor on a number you already have' },
        { reason: 'the invoice text tries to give orders to the payment system', resolution: 'read the invoice text, then ask the vendor for a clean copy' },
      ],
    },
  },
  data_handling: {
    storage: {
      database: {
        type: 'PostgreSQL',
        location: 'us-ord (Chicago)',
        description: 'Audit trail and policy records for every decision',
      },
      object_storage: {
        configured: true,
        region: 'us-ord-1',
        description: 'Invoice attachments and supporting documents',
      },
    },
    network_isolation: {
      vpc_private: {
        model_server: 'Model inference server runs in VPC-private subnet (10.0.3.0/24)',
        decider_server: 'Strands Decider server runs in VPC-private subnet',
        database: 'PostgreSQL accessible only from app tier (10.0.4.0/24)',
      },
      firewall: {
        default_deny_inbound: true,
        allowed_inbound: ['443/TCP (HTTPS)', '80/TCP (redirect)'],
        description: 'Cloud Firewall with explicit allow-list',
      },
    },
    llm_data_handling: {
      deterministic_path: {
        description: 'When Decider/deterministic path is used, no invoice data is sent to third-party LLM.',
        decider_active: true,
        llm_mode: 'offline',
      },
      hosted_inference: {
        provider: 'Akamai Cloud Inference',
        base_url: 'https://ws.akamai-workshops.com/v1',
        description: 'When LLM is used, it is Akamai-hosted inference.',
      },
    },
    demo_data: {
      description: 'All demo/test data is synthetic; no real customer data in demos.',
      synthetic_vendors: true,
      synthetic_invoices: true,
    },
  },
  infrastructure: {
    deployment: {
      provider: 'Akamai Cloud Computing (Linode)',
      region: 'us-ord (Chicago)',
      products: [
        'Dedicated-CPU Linode',
        'Akamai VPC',
        'Akamai Cloud Firewall',
        'Akamai NodeBalancer',
        'Akamai Managed Database (PostgreSQL)',
        'Akamai Object Storage',
        'Akamai Cloud Inference',
      ],
    },
    settlement: {
      adapter: 'xrpl',
      network: 'XRPL Testnet',
      description: 'Settlement adapter for payment execution',
    },
    model: {
      name: 'vouch-risk',
      scorer: 'auto',
      description: 'PyTorch fraud detection model with LIME explanations',
    },
  },
  not_yet_implemented: {
    description: 'Honest disclosure of what Vouch does NOT have yet.',
    items: [
      { item: 'SOC 2 certification', status: 'not_started', description: 'No SOC 2 Type I or Type II audit has been performed.' },
      { item: 'Third-party penetration test', status: 'not_started', description: 'No external pen test; only internal red-team suite.' },
      { item: 'Production settlement', status: 'testnet_only', description: 'Settlement is on XRPL Testnet only; no real money movement.' },
      { item: 'Intake shared secret validation', status: 'not_implemented', description: 'Intake endpoint does not validate shared secret from email forwarders.' },
      { item: 'Multi-tenant isolation', status: 'not_implemented', description: 'Single-tenant deployment only; no multi-org isolation.' },
      { item: 'Encryption at rest', status: 'provider_managed', description: 'Relies on provider-level encryption; no customer-managed keys.' },
    ],
  },
}
