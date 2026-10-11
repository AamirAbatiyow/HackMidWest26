"""Parse SPF / DKIM / DMARC verdicts from Authentication-Results and Received-SPF headers."""

from __future__ import annotations

import re

from ..contracts import AuthResults

_RESULT_RE = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)
_DKIM_D_RE = re.compile(r"header\.d\s*=\s*([A-Za-z0-9.-]+)", re.IGNORECASE)
_SPF_FROM_RE = re.compile(
    r"(?:smtp\.mailfrom|envelope-from)\s*=\s*(?:[^@\s;]+@)?([A-Za-z0-9.-]+)", re.IGNORECASE
)
_VALID = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "policy", "bestguesspass"}


def parse_auth_results(auth_headers: list[str], received_spf: str = "") -> AuthResults:
    """Combine every Authentication-Results header; the first verdict per mechanism wins
    (the topmost header is the receiving MTA's own evaluation)."""
    res = AuthResults(raw=list(auth_headers))
    found: dict[str, str] = {}
    for header in auth_headers:
        for mech, verdict in _RESULT_RE.findall(header):
            mech, verdict = mech.lower(), verdict.lower()
            if verdict in _VALID and mech not in found:
                found[mech] = verdict
        if res.dkim_domain is None:
            m = _DKIM_D_RE.search(header)
            if m:
                res.dkim_domain = m.group(1).lower()
        if res.spf_domain is None:
            m = _SPF_FROM_RE.search(header)
            if m:
                res.spf_domain = m.group(1).lower()
    if "spf" not in found and received_spf:
        m = re.match(r"\s*([a-z]+)", received_spf, re.IGNORECASE)
        if m and m.group(1).lower() in _VALID:
            found["spf"] = m.group(1).lower()
        if res.spf_domain is None:
            m2 = _SPF_FROM_RE.search(received_spf)
            if m2:
                res.spf_domain = m2.group(1).lower()
    res.spf = found.get("spf", "none")
    res.dkim = found.get("dkim", "none")
    res.dmarc = found.get("dmarc", "none")
    return res
