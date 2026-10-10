"""Synthetic vendor directory for the demo (no real companies, accounts or people)."""

from __future__ import annotations

from datetime import date, timedelta

from ..models import BankAccount, PastPayment, Vendor


def build_directory(today: date) -> list[Vendor]:
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    return [
        Vendor(
            id="v-reyes",
            name="Reyes Packaging",
            city="Mexico City",
            country="MX",
            since=date(2023, 2, 14),
            payments_completed=41,
            domains=["reyespackaging.mx"],
            tax_id_digits="230214001",
            phone_digits="525512345678",
            address="Av. Insurgentes Sur 1602, Mexico City",
            contact_name="Lucía Reyes",
            contact_phone_masked="+52 55 ···5678",
            bank_accounts=[BankAccount(digits="012180001234567891", country="MX", since=date(2023, 2, 14))],
            typical_amount_cents=600_000,
            history=[
                PastPayment(
                    date=d(31), amount_cents=590_000, invoice_number="RP-10391", detail="settled in 38 s"
                ),
                PastPayment(date=d(62), amount_cents=615_000, invoice_number="RP-10302"),
            ],
            onboarding_note="Bank account verified by call-back",
        ),
        Vendor(
            id="v-warsaw",
            name="Warsaw Steel Sp. z o.o.",
            city="Warsaw",
            country="PL",
            since=date(2021, 9, 3),
            payments_completed=58,
            domains=["warsawsteel.pl"],
            tax_id_digits="5252345678",
            phone_digits="48221234118",
            address="ul. Hutnicza 12, 03-100 Warszawa",
            contact_name="Marta Kowalski",
            contact_phone_masked="+48 22 ···118",
            bank_accounts=[
                BankAccount(digits="PL61109010140000071219812874", country="PL", since=date(2021, 9, 3)),
                BankAccount(
                    digits="DE89370400440532013000",
                    country="DE",
                    since=d(2),
                    verified_by_callback=False,
                    requested_by="finance.ws@warsawsteel-eu.com",
                ),
            ],
            typical_amount_cents=1_180_000,
            history=[
                PastPayment(
                    date=d(29),
                    amount_cents=1_140_000,
                    invoice_number="WS-2026-0871",
                    detail="previous bank account",
                ),
                PastPayment(date=d(60), amount_cents=1_230_000, invoice_number="WS-2026-0812"),
            ],
            onboarding_note="Bank account verified by call-back",
        ),
        Vendor(
            id="v-midwest",
            name="Midwest Pallets",
            city="Kansas City",
            country="US",
            since=date(2022, 5, 20),
            payments_completed=73,
            domains=["midwestpallets.com"],
            tax_id_digits="471234567",
            phone_digits="8165550143",
            address="4100 Front St, Kansas City, MO 64120",
            contact_name="Tom Avery",
            contact_phone_masked="(816) ···0143",
            bank_accounts=[BankAccount(digits="001234567890", country="US", since=date(2022, 5, 20))],
            typical_amount_cents=495_000,
            history=[
                PastPayment(date=d(33), amount_cents=495_000, invoice_number="MP-5488"),
                PastPayment(date=d(64), amount_cents=495_000, invoice_number="MP-5450"),
            ],
        ),
        Vendor(
            id="v-brightline",
            name="Brightline Supply",
            city="Overland Park",
            country="US",
            since=date(2024, 11, 8),
            payments_completed=9,
            domains=["brightlinesupply.com"],
            tax_id_digits="839876543",
            phone_digits="9135550177",
            address="7300 W 110th St, Overland Park, KS 66210",
            contact_name="Priya Natarajan",
            contact_phone_masked="(913) ···0177",
            bank_accounts=[BankAccount(digits="44556677889", country="US", since=date(2024, 11, 8))],
            typical_amount_cents=950_000,
            history=[PastPayment(date=d(40), amount_cents=960_000, invoice_number="BL-3251")],
        ),
        Vendor(
            id="v-nova",
            name="Nova Trade LLC",
            city="Wilmington",
            country="US",
            since=d(6),
            payments_completed=0,
            domains=["novatrade-llc.com"],
            tax_id_digits=None,
            phone_digits="8165550192",
            address="1201 N Orange St, Suite 600, Wilmington, DE 19801",
            bank_accounts=[
                BankAccount(digits="998877664471", country="US", since=d(6), verified_by_callback=False)
            ],
            onboarding_note="Via email request, not yet called back",
        ),
        Vendor(
            id="v-apex",
            name="Apex Supply Co.",
            city="Wilmington",
            country="US",
            since=d(40),
            payments_completed=1,
            domains=["apexsupplyco.net"],
            phone_digits="8165550192",
            address="2093 Philadelphia Pike, Claymont, DE 19703",
            bank_accounts=[
                BankAccount(digits="998877664471", country="US", since=d(40), verified_by_callback=False)
            ],
            in_queue=False,
        ),
        Vendor(
            id="v-delta",
            name="Delta Freight LLC",
            city="Wilmington",
            country="US",
            since=d(25),
            payments_completed=1,
            domains=["deltafreight-llc.com"],
            phone_digits="3025550111",
            address="1201 N Orange St, Suite 600, Wilmington, DE 19801",
            bank_accounts=[
                BankAccount(digits="998877664471", country="US", since=d(25), verified_by_callback=False)
            ],
            in_queue=False,
        ),
        Vendor(
            id="v-santa-rita",
            name="Café Santa Rita",
            city="Belo Horizonte",
            country="BR",
            since=d(4),
            payments_completed=0,
            domains=["cafesantarita.com.br"],
            tax_id_digits="12345678000195",
            phone_digits="553133334444",
            address="Rua da Bahia 1148, Belo Horizonte, MG",
            contact_name="Ana Ribeiro",
            contact_phone_masked="+55 31 ···4444",
            bank_accounts=[
                BankAccount(digits="0011234567890", country="BR", since=d(4), verified_by_callback=True)
            ],
            verified_by_callback=True,
            registration_verified=True,
            onboarding_note="CNPJ registration checked",
        ),
    ]
