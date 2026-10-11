"""Deterministic sender check: SPF/DKIM/DMARC results, lookalike domains, reply-to and display-name
mismatches. Runs as a graph node right after intake and feeds the kernel checks, the policy and the
owner-facing evidence. It never denies: a suspicious sender places the card on hold with a next step."""

from __future__ import annotations

from ..contracts import EmailEnvelope, SenderFindings, email_domain
from ..domain import Vendor
from .auth_results import parse_auth_results
from .lookalike import FREEMAIL, check_lookalike, registrable_label


def _name_tokens(name: str) -> set[str]:
    stop = {"inc", "llc", "ltd", "co", "sp", "z", "o", "the", "and", "de", "sa", "gmbh", "corp", "cv"}
    return {
        t
        for t in "".join(ch if ch.isalnum() else " " for ch in name.lower()).split()
        if t not in stop and len(t) > 2
    }


def vendor_domains(vendor: Vendor) -> list[str]:
    d = email_domain(vendor.email)
    return [d] if d else []


def check_sender(
    envelope: EmailEnvelope | None,
    vendors: list[Vendor],
    claimed_vendor: Vendor | None = None,
) -> SenderFindings:
    """Evaluate who sent the invoice. `claimed_vendor` is the master-file vendor the invoice resolved
    to (if any), used to detect new or mismatched senders for a known vendor."""
    findings = SenderFindings()
    if envelope is None or not envelope.from_addr:
        findings.flags.append("no_email_envelope")
        return findings
    findings.checked = True
    known_domains = sorted({d for v in vendors for d in vendor_domains(v) if d not in FREEMAIL})
    findings.from_addr = envelope.from_addr
    findings.from_domain = email_domain(envelope.from_addr) or ""
    findings.reply_to = envelope.reply_to
    findings.reply_to_domain = email_domain(envelope.reply_to) or ""
    findings.auth = parse_auth_results(envelope.authentication_results, envelope.received_spf)
    a = findings.auth
    findings.auth_pass = a.spf == "pass" and a.dkim == "pass" and a.dmarc in ("pass", "none", "bestguesspass")

    risk = 0.0
    if not envelope.authentication_results and not envelope.received_spf:
        findings.flags.append("no_authentication_results")
        risk += 0.15
    if a.spf in ("fail", "softfail", "permerror"):
        findings.flags.append(f"spf_{a.spf}")
        risk += 0.25
    if a.dkim in ("fail", "permerror"):
        findings.flags.append(f"dkim_{a.dkim}")
        risk += 0.25
    elif a.dkim == "none" and envelope.authentication_results:
        findings.flags.append("dkim_missing")
        risk += 0.1
    if a.dmarc == "fail":
        findings.flags.append("dmarc_fail")
        risk += 0.3
    if (
        a.dkim_domain
        and findings.from_domain
        and a.dkim_domain != findings.from_domain
        and registrable_label(a.dkim_domain) != registrable_label(findings.from_domain)
    ):
        findings.flags.append("dkim_domain_differs_from_from")
        risk += 0.15

    if findings.reply_to_domain and findings.reply_to_domain != findings.from_domain:
        findings.reply_to_mismatch = True
        findings.flags.append("reply_to_mismatch")
        risk += 0.3

    findings.lookalike = check_lookalike(findings.from_domain, known_domains)
    if findings.lookalike.is_lookalike:
        findings.flags.append("lookalike_domain")
        risk += 0.45
    if findings.reply_to_domain:
        rt = check_lookalike(findings.reply_to_domain, known_domains)
        if rt.is_lookalike:
            findings.flags.append("reply_to_lookalike_domain")
            risk += 0.2

    if findings.from_domain in FREEMAIL:
        findings.flags.append("freemail_sender")
        risk += 0.2 if claimed_vendor and claimed_vendor.history else 0.05

    if claimed_vendor is not None:
        domains = vendor_domains(claimed_vendor)
        if domains and findings.from_domain and findings.from_domain not in domains:
            findings.flags.append("new_sender_for_known_vendor")
            risk += 0.25
        if envelope.from_name:
            claimed = _name_tokens(claimed_vendor.name)
            shown = _name_tokens(envelope.from_name)
            if claimed and shown & claimed and findings.from_domain not in domains:
                findings.display_name_mismatch = True
                findings.flags.append("display_name_mismatch")
                risk += 0.2
    findings.risk = round(min(1.0, risk), 3)
    return findings
