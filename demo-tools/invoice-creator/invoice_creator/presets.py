"""Demo scenarios. All vendors, people, accounts, tax ids and domains are invented.

The vendor details mirror the synthetic vendor directory the Vouch backend seeds
(``backend/projects/vouch/src/vouch/demo/vendors.py``): same domains, bank accounts, phone
numbers and addresses, so the backend's detectors react the way each scenario intends.
Invoice numbers are deliberately different from the backend's own sample files so a demo
send is never mistaken for a re-send of a seeded sample.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from .models import AuthSimulation, BankDetails, Invoice, LineItem, OutputFormat, RemitTo, SenderIdentity


class SenderOption(BaseModel):
    kind: Literal["legit", "lookalike"]
    label: str
    from_name: str
    from_addr: str
    reply_to: str = ""


class Preset(BaseModel):
    key: str
    group: str  # a … f
    title: str
    vendor: str
    summary: str  # what the scenario demonstrates
    expected: str  # what Vouch is expected to do
    hint: str = ""  # operator instruction shown under the preset
    format: OutputFormat = "pdf"
    invoice: Invoice
    sender: SenderIdentity
    sender_options: list[SenderOption] = Field(default_factory=list)
    follow_up: str | None = None  # key of the next step (duplicate re-send, second half)
    follow_up_label: str = ""
    hidden: bool = False  # follow-ups are not listed as top-level buttons


def _iso(d: date) -> str:
    return d.isoformat()


def build_presets(today: date | None = None) -> list[Preset]:
    today = today or date.today()
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    presets: list[Preset] = []

    # ------------------------------------------------------------------ (a) legit ----
    reyes_invoice = Invoice(
        vendor_name="Reyes Packaging",
        vendor_email="ar@reyespackaging.mx",
        invoice_number="RP-10517",
        currency="USD",
        amount=6400.00,
        invoice_date=d(-1),
        due_date=d(5),
        po_number="7744",
        description="Corrugated shipping cartons, 8,000 units",
        line_items=[LineItem(description="Corrugated shipping cartons", quantity=8000, unit_price=0.80)],
        bank=BankDetails(
            bank_name="BBVA Mexico",
            account_label="CLABE",
            account_number="012180001234567891",
            routing_label="SWIFT",
            routing_number="BCMRMXMMPYM",
        ),
        remit_to=RemitTo(
            address="Av. Insurgentes Sur 1602, Mexico City",
            phone="+52 55 1234 5678",
            tax_id_label="RFC",
            tax_id="RPA230214001",
            contact_name="Lucía Reyes",
        ),
        notes="Same account as always. Gracias, Lucía",
    )
    presets.append(
        Preset(
            key="reyes",
            group="a",
            title="Legit vendor",
            vendor="Reyes Packaging · Mexico City · $6,400",
            summary="Known vendor, authenticated sender, bank account matches 41 past payments.",
            expected="Vouched, fast-pay eligible.",
            format="pdf",
            invoice=reyes_invoice,
            sender=SenderIdentity(
                from_name="Reyes Packaging AR",
                from_addr="ar@reyespackaging.mx",
                subject="Invoice RP-10517 — cartons PO 7744",
                body=(
                    "Hola, attached is invoice RP-10517 for PO 7744. Same account as always.\n\n"
                    "Gracias,\nLucía Reyes\nAccounts Receivable, Reyes Packaging"
                ),
            ),
            sender_options=[
                SenderOption(
                    kind="legit",
                    label="Legit domain",
                    from_name="Reyes Packaging AR",
                    from_addr="ar@reyespackaging.mx",
                ),
                SenderOption(
                    kind="lookalike",
                    label="Lookalike domain",
                    from_name="Reyes Packaging AR",
                    from_addr="ar@reyespackaging-mx.com",
                ),
            ],
        )
    )

    # ---------------------------------------------------- (b) bank-detail swap ----
    warsaw_invoice = Invoice(
        vendor_name="Warsaw Steel Sp. z o.o.",
        vendor_email="finance.ws@warsawsteel-eu.com",
        invoice_number="WS-2026-0931",
        currency="USD",
        amount=12000.00,
        invoice_date=d(0),
        due_date=d(2),
        po_number="",
        description="Structural steel beams, lot 19",
        line_items=[
            LineItem(description="Structural steel beams HEB 200, lot 19", quantity=24, unit_price=500.00)
        ],
        bank=BankDetails(
            bank_name="Commerzbank AG",
            account_label="IBAN",
            account_number="DE89 3704 0044 0532 0130 00",
            routing_label="SWIFT",
            routing_number="COBADEFFXXX",
        ),
        remit_to=RemitTo(
            address="ul. Hutnicza 12, 03-100 Warszawa",
            phone="+48 22 123 41 18",
            tax_id_label="NIP",
            tax_id="5252345678",
            contact_name="Marta Kowalski",
        ),
        notes=(
            "URGENT: our banking details have changed effective immediately. Kindly remit to the new "
            "account above. Payment must be received within 24 hours to avoid shipment delays."
        ),
    )
    presets.append(
        Preset(
            key="warsaw",
            group="b",
            title="Bank-detail swap / account takeover",
            vendor="Warsaw Steel Sp. z o.o. · $12,000",
            summary=(
                "Known vendor, but the invoice is sent from a lookalike domain (warsawsteel-eu.com vs "
                "warsawsteel.pl), replies go to a freemail address, the IBAN is new and unverified, and "
                "the note pushes urgency. The lookalike domain authenticates for itself, so SPF/DKIM pass."
            ),
            expected="Verify — changed bank details, hold until call-back on the number on file.",
            format="body",
            invoice=warsaw_invoice,
            sender=SenderIdentity(
                from_name="Warsaw Steel Finance",
                from_addr="finance.ws@warsawsteel-eu.com",
                reply_to="ws.accounts.update@protonmail.com",
                subject="Invoice WS-2026-0931 — UPDATED BANK DETAILS, urgent",
                body=(
                    "Dear Accounts Payable,\n\nPlease find below our invoice. NOTE: our banking details have "
                    "changed, kindly remit to the new account. We need this settled within 24 hours.\n\n"
                    "Kind regards,\nMarta Kowalski\nFinance, Warsaw Steel"
                ),
                auth=AuthSimulation(spf="pass", dkim="pass", dmarc="none"),
            ),
            sender_options=[
                SenderOption(
                    kind="legit",
                    label="Legit domain",
                    from_name="Warsaw Steel AR",
                    from_addr="ar@warsawsteel.pl",
                ),
                SenderOption(
                    kind="lookalike",
                    label="Lookalike domain",
                    from_name="Warsaw Steel Finance",
                    from_addr="finance.ws@warsawsteel-eu.com",
                    reply_to="ws.accounts.update@protonmail.com",
                ),
            ],
        )
    )

    # -------------------------------------------------------- (c) duplicate ----
    midwest_invoice = Invoice(
        vendor_name="Midwest Pallets",
        vendor_email="ap@midwestpallets.com",
        invoice_number="MP-5533",
        currency="USD",
        amount=4950.00,
        invoice_date=d(0),
        due_date=d(7),
        po_number="",
        description="48x40 GMA pallets, monthly order",
        line_items=[LineItem(description="48x40 GMA pallets", quantity=550, unit_price=9.00)],
        bank=BankDetails(
            bank_name="Commerce Bank",
            account_label="Account Number",
            account_number="001234567890",
            routing_label="Routing Number",
            routing_number="101000019",
        ),
        remit_to=RemitTo(
            address="4100 Front St, Kansas City, MO 64120",
            phone="(816) 555-0143",
            tax_id_label="EIN",
            tax_id="47-1234567",
            contact_name="Tom Avery",
        ),
        notes="Monthly pallet order. Thanks, Tom",
    )
    midwest_sender_options = [
        SenderOption(
            kind="legit", label="Legit domain", from_name="Midwest Pallets", from_addr="ap@midwestpallets.com"
        ),
        SenderOption(
            kind="lookalike",
            label="Lookalike domain",
            from_name="Midwest Pallets",
            from_addr="ap@midwest-pallets.com",
        ),
    ]
    presets.append(
        Preset(
            key="midwest",
            group="c",
            title="Duplicate invoice",
            vendor="Midwest Pallets · $4,950 × 2",
            summary=(
                "Known vendor, regular monthly amount, Excel attachment. "
                "The same invoice number arrives twice."
            ),
            expected="First copy vouched; the re-send is flagged as a duplicate (quick check).",
            hint="Send it, then load the re-send (same invoice number) and send again.",
            format="xlsx",
            invoice=midwest_invoice,
            sender=SenderIdentity(
                from_name="Midwest Pallets",
                from_addr="ap@midwestpallets.com",
                subject="Invoice MP-5533",
                body="Monthly pallet order attached.\n\nThanks,\nTom Avery\nMidwest Pallets",
            ),
            sender_options=midwest_sender_options,
            follow_up="midwest-resend",
            follow_up_label="Load the re-send (duplicate MP-5533)",
        )
    )
    presets.append(
        Preset(
            key="midwest-resend",
            group="c",
            title="Duplicate invoice — re-send",
            vendor="Midwest Pallets · $4,950 (same MP-5533)",
            summary="Identical invoice re-sent 'in case the first one did not come through'.",
            expected="Quick check — duplicate of the earlier MP-5533.",
            format="xlsx",
            invoice=midwest_invoice,
            sender=SenderIdentity(
                from_name="Midwest Pallets",
                from_addr="ap@midwestpallets.com",
                subject="Re: Invoice MP-5533",
                body="Resending in case the first one did not come through.\n\nTom",
            ),
            sender_options=midwest_sender_options,
            hidden=True,
        )
    )

    # ----------------------------------------------------------- (d) split ----
    def brightline(inv_no: str, half: str) -> Invoice:
        return Invoice(
            vendor_name="Brightline Supply",
            vendor_email="billing@brightlinesupply.com",
            invoice_number=inv_no,
            currency="USD",
            amount=4900.00,
            invoice_date=d(0),
            due_date=d(10),
            po_number="BL-PO-2210",
            description=f"Janitorial supplies, {half}",
            line_items=[
                LineItem(description="Commercial floor cleaner, 5 gal", quantity=40, unit_price=62.50),
                LineItem(description="Nitrile gloves, case of 1,000", quantity=30, unit_price=80.00),
            ],
            bank=BankDetails(
                bank_name="UMB Bank",
                account_label="Account Number",
                account_number="44556677889",
                routing_label="Routing Number",
                routing_number="101089742",
            ),
            remit_to=RemitTo(
                address="7300 W 110th St, Overland Park, KS 66210",
                phone="(913) 555-0177",
                tax_id_label="EIN",
                tax_id="83-9876543",
                contact_name="Priya Natarajan",
            ),
            notes=f"Order split into two invoices for your convenience ({half}).",
        )

    brightline_sender_options = [
        SenderOption(
            kind="legit",
            label="Legit domain",
            from_name="Brightline Supply",
            from_addr="billing@brightlinesupply.com",
        ),
        SenderOption(
            kind="lookalike",
            label="Lookalike domain",
            from_name="Brightline Supply",
            from_addr="billing@brightlinesupply-billing.com",
        ),
    ]
    presets.append(
        Preset(
            key="brightline-1",
            group="d",
            title="Split invoice under the $5,000 limit",
            vendor="Brightline Supply · 2 × $4,900",
            summary=(
                "A $9,800 order is billed as two $4,900 invoices minutes apart, each just under the "
                "owner's $5,000 approval limit."
            ),
            expected="Both halves flagged as a split-under-limit pattern (quick check).",
            hint="Send the first half, then load and send the second half within the hour.",
            format="csv",
            invoice=brightline("BL-3312", "first half"),
            sender=SenderIdentity(
                from_name="Brightline Supply",
                from_addr="billing@brightlinesupply.com",
                subject="Invoice BL-3312",
                body=(
                    "Invoice BL-3312 attached (first half of the order).\n\n"
                    "Priya Natarajan\nBrightline Supply"
                ),
            ),
            sender_options=brightline_sender_options,
            follow_up="brightline-2",
            follow_up_label="Load the second half (BL-3313)",
        )
    )
    presets.append(
        Preset(
            key="brightline-2",
            group="d",
            title="Split invoice — second half",
            vendor="Brightline Supply · $4,900 (BL-3313)",
            summary="Second $4,900 invoice from the same vendor, minutes after the first.",
            expected="Quick check — combined $9,800 exceeds the approval limit.",
            format="csv",
            invoice=brightline("BL-3313", "second half"),
            sender=SenderIdentity(
                from_name="Brightline Supply",
                from_addr="billing@brightlinesupply.com",
                subject="Invoice BL-3313",
                body=(
                    "Invoice BL-3313 attached (second half of the order).\n\n"
                    "Priya Natarajan\nBrightline Supply"
                ),
            ),
            sender_options=brightline_sender_options,
            hidden=True,
        )
    )

    # ------------------------------------------------------ (e) vendor ring ----
    nova_invoice = Invoice(
        vendor_name="Nova Trade LLC",
        vendor_email="billing@novatrade-llc.com",
        invoice_number="NT-0002",
        currency="USD",
        amount=7200.00,
        invoice_date=d(0),
        due_date=d(6),
        po_number="",
        description="Consulting services, Q4 market entry study",
        line_items=[LineItem(description="Consulting services (hours)", quantity=48, unit_price=150.00)],
        bank=BankDetails(
            bank_name="First Keystone Bank",
            account_label="Account Number",
            account_number="998877664471",
            routing_label="Routing Number",
            routing_number="021000021",
        ),
        remit_to=RemitTo(
            address="1201 N Orange St, Suite 600, Wilmington, DE 19801",
            phone="(816) 555-0192",
            tax_id_label="EIN",
            tax_id="",
            contact_name="J. Mercer",
        ),
        notes="Please process at your earliest convenience.",
    )
    presets.append(
        Preset(
            key="nova",
            group="e",
            title="Fake vendor ring",
            vendor="Nova Trade LLC · $7,200",
            summary=(
                "Brand-new vendor whose bank account, phone number and virtual-office address are shared "
                "with two other recently added vendors (Apex Supply Co., Delta Freight LLC)."
            ),
            expected="Verify — unrecognized vendor, ring graph shows the shared bank / phone / address.",
            format="png",
            invoice=nova_invoice,
            sender=SenderIdentity(
                from_name="Nova Trade Billing",
                from_addr="billing@novatrade-llc.com",
                subject="Invoice NT-0002 — consulting services",
                body=(
                    "Hello,\n\nPlease find attached invoice NT-0002 for consulting services.\n\n"
                    "Best regards,\nJ. Mercer\nNova Trade LLC"
                ),
            ),
            sender_options=[
                SenderOption(
                    kind="legit",
                    label="Vendor's own domain",
                    from_name="Nova Trade Billing",
                    from_addr="billing@novatrade-llc.com",
                ),
                SenderOption(
                    kind="lookalike",
                    label="Lookalike domain",
                    from_name="Nova Trade Billing",
                    from_addr="accounts@nova-trade-llc.com",
                ),
            ],
        )
    )

    # -------------------------------------------------- (f) honest new vendor ----
    santa_rita_invoice = Invoice(
        vendor_name="Café Santa Rita",
        vendor_email="vendas@cafesantarita.com.br",
        invoice_number="CSR-0002",
        currency="USD",
        amount=1850.00,
        invoice_date=d(0),
        due_date=d(14),
        po_number="",
        description="Specialty coffee beans, lot BH-23",
        line_items=[
            LineItem(description="Specialty coffee beans, lot BH-23 (kg)", quantity=100, unit_price=18.50)
        ],
        bank=BankDetails(
            bank_name="Banco do Brasil",
            account_label="Account Number",
            account_number="0011234567890",
            routing_label="SWIFT",
            routing_number="BRASBRRJBHE",
        ),
        remit_to=RemitTo(
            address="Rua da Bahia 1148, Belo Horizonte, MG, Brazil",
            phone="+55 31 3333 4444",
            tax_id_label="CNPJ",
            tax_id="12.345.678/0001-95",
            contact_name="Ana Ribeiro",
        ),
        notes="Obrigada! First order — looking forward to working with you. Ana",
    )
    presets.append(
        Preset(
            key="santa-rita",
            group="f",
            title="Honest brand-new small vendor",
            vendor="Café Santa Rita · Brazil · $1,850",
            summary=(
                "First invoice from a small new vendor: registration (CNPJ) checked, bank verified by "
                "call-back, amount under the new-vendor limit, authenticated sender."
            ),
            expected="Vouched — a new vendor is not automatically suspicious.",
            format="pdf",
            invoice=santa_rita_invoice,
            sender=SenderIdentity(
                from_name="Café Santa Rita",
                from_addr="vendas@cafesantarita.com.br",
                subject="Invoice CSR-0002 — specialty coffee, lot BH-23",
                body=(
                    "Olá!\n\nAttached is our first invoice, CSR-0002, for the coffee shipment "
                    "(lot BH-23).\n\n"
                    "Obrigada,\nAna Ribeiro\nCafé Santa Rita"
                ),
            ),
            sender_options=[
                SenderOption(
                    kind="legit",
                    label="Legit domain",
                    from_name="Café Santa Rita",
                    from_addr="vendas@cafesantarita.com.br",
                ),
                SenderOption(
                    kind="lookalike",
                    label="Lookalike domain",
                    from_name="Café Santa Rita",
                    from_addr="vendas@cafesantarita.com",
                ),
            ],
        )
    )
    return presets


def preset_map(today: date | None = None) -> dict[str, Preset]:
    return {p.key: p for p in build_presets(today)}


def get_preset(key: str, today: date | None = None) -> Preset:
    presets = preset_map(today)
    if key not in presets:
        raise KeyError(f"unknown preset {key!r}; known: {', '.join(presets)}")
    return presets[key]


def demo_sequence() -> list[str]:
    """Every preset in the order a full demo sends them (follow-ups right after their parent)."""
    order: list[str] = []
    for p in build_presets():
        if p.hidden:
            continue
        order.append(p.key)
        if p.follow_up:
            order.append(p.follow_up)
    return order
