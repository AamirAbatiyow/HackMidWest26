"""Presets: every scenario exists, lines up with the backend's synthetic vendor directory and
carries the signals its detector needs."""

from __future__ import annotations

from datetime import date

import pytest

from invoice_creator.presets import build_presets, demo_sequence, get_preset, preset_map

TODAY = date(2026, 10, 11)

# Values the Vouch backend seeds in its vendor directory (backend/.../demo/vendors.py).
BACKEND_RING_BANK = "998877664471"
BACKEND_RING_PHONE_DIGITS = "8165550192"
BACKEND_RING_ADDRESS = "1201 N Orange St, Suite 600, Wilmington, DE 19801"
BACKEND_SAMPLE_INVOICE_NUMBERS = {
    "RP-10482", "WS-2026-0917", "MP-5521", "BL-3307", "BL-3308", "NT-0001", "CSR-0001",
}


def digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def test_six_scenarios_a_to_f_plus_follow_ups():
    presets = build_presets(TODAY)
    groups = sorted({p.group for p in presets})
    assert groups == ["a", "b", "c", "d", "e", "f"]
    visible = [p for p in presets if not p.hidden]
    assert [p.group for p in visible] == ["a", "b", "c", "d", "e", "f"]
    assert len({p.key for p in presets}) == len(presets)
    assert demo_sequence() == [
        "reyes",
        "warsaw",
        "midwest",
        "midwest-resend",
        "brightline-1",
        "brightline-2",
        "nova",
        "santa-rita",
    ]
    for p in presets:
        if p.follow_up:
            assert preset_map(TODAY)[p.follow_up].hidden


def test_invoice_numbers_do_not_collide_with_backend_samples():
    for p in build_presets(TODAY):
        assert p.invoice.invoice_number not in BACKEND_SAMPLE_INVOICE_NUMBERS


def test_amounts_and_line_items_are_consistent():
    expected = {
        "reyes": 6400.00,
        "warsaw": 12000.00,
        "midwest": 4950.00,
        "midwest-resend": 4950.00,
        "brightline-1": 4900.00,
        "brightline-2": 4900.00,
        "nova": 7200.00,
        "santa-rita": 1850.00,
    }
    for p in build_presets(TODAY):
        assert p.invoice.amount == expected[p.key], p.key
        assert p.invoice.line_total == p.invoice.amount, p.key
        assert p.invoice.amount_cents == round(expected[p.key] * 100)
        assert p.invoice.due_date >= p.invoice.invoice_date
        assert p.invoice.invoice_date <= TODAY


def test_legit_vendor_matches_known_history():
    p = get_preset("reyes", TODAY)
    assert p.invoice.vendor_name == "Reyes Packaging"
    assert p.sender.from_addr.endswith("@reyespackaging.mx")
    assert p.invoice.bank.account_label == "CLABE"
    assert p.invoice.bank.account_number == "012180001234567891"  # the account on file
    auth = p.sender.auth
    assert auth.enabled and (auth.spf, auth.dkim, auth.dmarc) == ("pass",) * 3
    assert not p.sender.reply_to
    assert "fast-pay" in p.expected.lower()


def test_bank_swap_scenario_has_lookalike_domain_reply_to_new_iban_and_urgency():
    p = get_preset("warsaw", TODAY)
    legit = next(o for o in p.sender_options if o.kind == "legit")
    look = next(o for o in p.sender_options if o.kind == "lookalike")
    assert legit.from_addr.split("@")[1] == "warsawsteel.pl"
    assert look.from_addr.split("@")[1] == "warsawsteel-eu.com"
    assert p.sender.from_addr == look.from_addr  # the preset sends from the lookalike by default
    assert p.sender.reply_to.endswith("@protonmail.com")
    assert p.invoice.bank.account_label == "IBAN"
    assert digits(p.invoice.bank.account_number) == digits("DE89 3704 0044 0532 0130 00")
    assert "URGENT" in p.invoice.notes and "24 hours" in p.invoice.notes
    assert (p.sender.auth.spf, p.sender.auth.dkim, p.sender.auth.dmarc) == ("pass", "pass", "none")
    assert p.format == "body"
    assert p.invoice.amount == 12000.00


def test_duplicate_scenario_reuses_the_invoice_number():
    first, again = get_preset("midwest", TODAY), get_preset("midwest-resend", TODAY)
    assert first.follow_up == "midwest-resend"
    assert first.invoice.invoice_number == again.invoice.invoice_number == "MP-5533"
    assert first.invoice.amount == again.invoice.amount
    assert first.invoice.model_dump() == again.invoice.model_dump()
    assert again.sender.subject.startswith("Re:")
    assert first.invoice.bank.account_number == "001234567890"
    assert first.format == "xlsx"


def test_split_scenario_sits_just_under_the_limit():
    limit = 5000.00
    a, b = get_preset("brightline-1", TODAY), get_preset("brightline-2", TODAY)
    assert a.follow_up == "brightline-2"
    assert a.invoice.invoice_number != b.invoice.invoice_number
    assert a.invoice.amount < limit and b.invoice.amount < limit
    assert a.invoice.amount + b.invoice.amount >= limit
    assert a.invoice.vendor_name == b.invoice.vendor_name == "Brightline Supply"
    assert a.invoice.bank.account_number == b.invoice.bank.account_number == "44556677889"
    assert a.format == b.format == "csv"


def test_ring_scenario_shares_bank_phone_and_address_with_backend_ring():
    p = get_preset("nova", TODAY)
    assert p.invoice.vendor_name == "Nova Trade LLC"
    assert p.invoice.bank.account_number == BACKEND_RING_BANK
    assert digits(p.invoice.remit_to.phone) == BACKEND_RING_PHONE_DIGITS
    assert p.invoice.remit_to.address == BACKEND_RING_ADDRESS
    assert p.invoice.remit_to.tax_id == ""  # no tax id on file
    assert p.format == "png"  # exercises the OCR path


def test_new_small_vendor_is_honest():
    p = get_preset("santa-rita", TODAY)
    assert p.invoice.vendor_name == "Café Santa Rita"
    assert p.invoice.amount == 1850.00 < 2500.00  # under the backend's new-vendor limit
    assert p.invoice.remit_to.tax_id_label == "CNPJ"
    assert p.invoice.bank.account_number == "0011234567890"
    assert p.sender.from_addr.endswith("@cafesantarita.com.br")
    assert (p.sender.auth.spf, p.sender.auth.dkim, p.sender.auth.dmarc) == ("pass",) * 3


def test_every_preset_offers_legit_and_lookalike_sender_options():
    for p in build_presets(TODAY):
        kinds = {o.kind for o in p.sender_options}
        assert kinds == {"legit", "lookalike"}, p.key
        legit = next(o for o in p.sender_options if o.kind == "legit")
        look = next(o for o in p.sender_options if o.kind == "lookalike")
        assert legit.from_addr.split("@")[1] != look.from_addr.split("@")[1]
        assert p.sender.from_addr in {legit.from_addr, look.from_addr}


def test_dates_are_relative_to_today():
    a = get_preset("reyes", date(2026, 1, 1))
    b = get_preset("reyes", date(2026, 6, 1))
    assert (a.invoice.due_date - a.invoice.invoice_date) == (b.invoice.due_date - b.invoice.invoice_date)
    assert a.invoice.due_date == date(2026, 1, 6)


def test_unknown_preset_raises():
    with pytest.raises(KeyError):
        get_preset("nope")
