"""Bank-detail change / account-takeover detector. Consumes the structured sender findings."""

from __future__ import annotations

from datetime import date

from ..models import BankChangeFindings, ParsedInvoice, SenderFindings, Vendor

RECENT_CHANGE_DAYS = 30


def detect_bank_change(
    parsed: ParsedInvoice,
    vendor: Vendor | None,
    sender: SenderFindings | None,
    today: date,
) -> BankChangeFindings:
    f = BankChangeFindings()
    if vendor is None:
        return f
    current = vendor.current_bank
    previous = vendor.previous_bank
    invoice_acct = parsed.bank_account_digits
    on_file = {b.digits for b in vendor.bank_accounts}

    if current and previous:
        days = (today - current.since).days
        if 0 <= days <= RECENT_CHANGE_DAYS:
            f.changed = True
            f.days_since_change = days
            f.requester_verified = current.verified_by_callback
            f.requested_by = current.requested_by
            f.country_changed = current.country != previous.country
            f.flags.append("bank_changed_recently")
            if not current.verified_by_callback:
                f.flags.append("change_not_verified_by_callback")
            if f.country_changed:
                f.flags.append("new_bank_in_different_country")

    if invoice_acct:
        f.invoice_account_matches_file = invoice_acct in on_file
        if not f.invoice_account_matches_file:
            f.changed = True
            f.requester_verified = False
            f.flags.append("invoice_lists_account_not_on_file")
        elif previous and invoice_acct == previous.digits and current and invoice_acct != current.digits:
            f.flags.append("invoice_lists_previous_account")

    score = 0.0
    if f.changed:
        score += 0.45
        if f.requester_verified is False:
            score += 0.25
        if f.country_changed:
            score += 0.1
        if sender is not None:
            score += 0.3 * sender.risk
            if "lookalike_domain" in sender.flags or "new_sender_for_known_vendor" in sender.flags:
                f.flags.append("change_came_from_new_or_lookalike_sender")
    f.account_takeover_score = round(min(1.0, score), 3)
    return f
