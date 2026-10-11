"""Deterministic sender check: authentication results, lookalike domains, reply-to mismatch, freemail."""

from __future__ import annotations

from vouch.contracts import EmailEnvelope
from vouch.demo import demo_vendors
from vouch.sender import (
    check_lookalike,
    check_sender,
    homoglyph_normalize,
    parse_auth_results,
    registrable_label,
)

VENDORS = demo_vendors()
PRAIRIE = next(v for v in VENDORS if v.id == "v-prairie")


def _env(from_addr: str, auth: str | None, reply_to: str = "", from_name: str = "") -> EmailEnvelope:
    return EmailEnvelope(
        from_addr=from_addr,
        from_name=from_name,
        reply_to=reply_to,
        authentication_results=[auth] if auth else [],
    )


def test_parse_auth_results_reads_spf_dkim_dmarc():
    res = parse_auth_results(
        [
            "mx.example; spf=pass smtp.mailfrom=prairiepackaging.com; dkim=pass header.d=prairiepackaging.com; dmarc=pass (p=REJECT) header.from=prairiepackaging.com"
        ]
    )
    assert (res.spf, res.dkim, res.dmarc) == ("pass", "pass", "pass")
    assert res.dkim_domain == "prairiepackaging.com"


def test_parse_auth_results_defaults_to_none_when_absent():
    res = parse_auth_results([])
    assert res.spf == "none" and res.dkim == "none" and res.dmarc == "none"


def test_registrable_label_and_homoglyphs():
    assert registrable_label("mail.prairiepackaging.com") == "prairiepackaging"
    assert registrable_label("prairiepackaging.co.uk") == "prairiepackaging"
    assert homoglyph_normalize("prairiepackag1ng") == homoglyph_normalize("prairiepackaglng")
    assert homoglyph_normalize("s0n0rafresh") == "sonorafresh"
    assert homoglyph_normalize("rneridian") == "meridian"
    assert homoglyph_normalize("prаiriepackaging") == "prairiepackaging"  # Cyrillic а


def test_lookalike_detects_hyphen_suffix_and_homoglyph_variants():
    known = ["prairiepackaging.com", "rheinland-gewuerze.de"]
    for dom in ("prairiepackaging-billing.com", "prairiepackaglng.com", "prairiepackaging.co"):
        finding = check_lookalike(dom, known)
        assert finding.is_lookalike, dom
        assert finding.closest_known_domain == "prairiepackaging.com"
    on_file = check_lookalike("prairiepackaging.com", known)
    assert on_file.is_known and not on_file.is_lookalike
    assert not check_lookalike("totallydifferentvendor.io", known).is_lookalike


def test_sender_clean_known_vendor_passes():
    auth = "mx; spf=pass smtp.mailfrom=prairiepackaging.com; dkim=pass header.d=prairiepackaging.com; dmarc=pass header.from=prairiepackaging.com"
    f = check_sender(
        _env("ar@prairiepackaging.com", auth, from_name="Prairie Packaging AR"), VENDORS, PRAIRIE
    )
    assert f.checked and f.auth_pass
    assert f.flags == []
    assert f.risk < 0.1


def test_sender_lookalike_with_reply_to_and_failed_dmarc_is_flagged():
    auth = "mx; spf=softfail smtp.mailfrom=prairiepackaging-billing.com; dkim=none; dmarc=fail header.from=prairiepackaging-billing.com"
    f = check_sender(
        _env(
            "ar@prairiepackaging-billing.com",
            auth,
            reply_to="ar@prairie-remit.net",
            from_name="Prairie Packaging AR",
        ),
        VENDORS,
        PRAIRIE,
    )
    assert not f.auth_pass and f.reply_to_mismatch
    for flag in ("spf_softfail", "dkim_missing", "dmarc_fail", "reply_to_mismatch", "lookalike_domain"):
        assert flag in f.flags, f.flags
    assert "new_sender_for_known_vendor" in f.flags
    assert f.lookalike and f.lookalike.closest_known_domain == "prairiepackaging.com"
    assert f.risk >= 0.6 and f.suspicious


def test_sender_freemail_for_business_vendor_is_flagged_but_not_lookalike():
    auth = (
        "mx; spf=pass smtp.mailfrom=proton.me; dkim=pass header.d=proton.me; dmarc=pass header.from=proton.me"
    )
    f = check_sender(_env("apex.global.trading@proton.me", auth), VENDORS, None)
    assert "freemail_sender" in f.flags
    assert not (f.lookalike and f.lookalike.is_lookalike)


def test_sender_without_envelope_is_not_checked():
    f = check_sender(None, VENDORS, PRAIRIE)
    assert not f.checked and f.flags == ["no_email_envelope"] and f.risk == 0.0


def test_sender_missing_authentication_results_adds_flag():
    f = check_sender(_env("ar@prairiepackaging.com", None), VENDORS, PRAIRIE)
    assert "no_authentication_results" in f.flags
    assert not f.auth_pass
