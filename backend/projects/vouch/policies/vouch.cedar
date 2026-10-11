// Vouch payment policy — Cedar, default deny.
//
// Anything not explicitly permitted below is denied. There is deliberately NO permit for
// Action::"deny_vendor", Action::"add_fee", Action::"round_amount", Action::"modify_amount"
// or for any principal of type Model: the model can never approve, move money, or change
// numbers. Vendors are never auto-denied; the automated system may only place a hold.

// P-01: the owner may approve a payment that is waiting on them.
@id("P-01")
permit(
  principal is Owner,
  action == Action::"approve",
  resource is Payment
) when {
  resource.lifecycle == "pending" || resource.lifecycle == "held" || resource.lifecycle == "appealed"
};

// P-02: the owner may hold or appeal (vouch for) any payment that is not settled.
@id("P-02")
permit(
  principal is Owner,
  action in [Action::"hold", Action::"appeal"],
  resource is Payment
) when { resource.lifecycle != "settled" };

// P-03: the automated system may place a hold, never a denial.
@id("P-03")
permit(
  principal is System,
  action == Action::"hold",
  resource is Payment
);

// P-04: fast pay (release without a click) only for vouched, eligible payments with no
// unverified bank change, within the approval limit.
@id("P-04")
permit(
  principal is System,
  action == Action::"fast_pay",
  resource is Payment
) when {
  resource.status == "vouched" &&
  resource.fast_pay_eligible &&
  !(resource.bank_changed && !resource.bank_change_verified) &&
  resource.amount_cents <= context.approval_limit_cents
};

// P-05: settlement requires a recorded owner approval on an approved payment.
@id("P-05")
permit(
  principal,
  action == Action::"settle",
  resource is Payment
) when {
  (principal is Owner || principal is System) &&
  resource.lifecycle == "approved" && context.owner_approval_recorded
};

// P-06: bank details change only after the owner's call-back verification.
@id("P-06")
permit(
  principal is Owner,
  action == Action::"change_bank_details",
  resource is Payment
) when { context.callback_verified };

// P-07: the system may read and explain; explanations never carry authority.
@id("P-07")
permit(
  principal is System,
  action in [Action::"read", Action::"explain"],
  resource is Payment
);

// P-08: a kickback email drafted for a sender (unreadable / unsupported / incomplete invoice) is sent
// only on the owner's say-so. No permit exists for System or Model, so nothing auto-sends a reply.
@id("P-08")
permit(
  principal is Owner,
  action in [Action::"approve_kickback", Action::"decline_kickback"],
  resource is Payment
) when { resource.lifecycle != "settled" };
