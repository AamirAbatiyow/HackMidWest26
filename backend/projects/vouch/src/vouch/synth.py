"""Seeded synthetic payables world: vendors, invoices, bank accounts, addresses, phones, tax ids, history.

Archetypes (labels are ground truth for training/evaluation only):
- honest_regular            long-tenure vendor, stable amounts, PO + delivery
- honest_new_small          (honest-unusual) new vendor, little history, small invoices
- honest_bank_change_ok     (honest-unusual) bank details changed, confirmed out-of-band
- honest_seasonal_spike     (honest-unusual) 2-3x usual amount, but with PO + delivery
- honest_shared_address     (honest-unusual) shares a business-park address with other vendors
- ato_bec                   real vendor hijacked: new bank/remit email, urgency, sometimes a master-file change
- insider_*                 duplicates, split invoices under the approval limit, creeping amounts, no PO/delivery
- fake_vendor               new synthetic vendor; invalid tax id, VOIP phone, virtual address; rings share
                            bank / address / phone / tax id
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from vouch.domain import Invoice, Labels, LineItem, PastPayment, RiskClass, Vendor
from vouch.identity import VOIP_PREFIXES, make_tax_id

COUNTRIES = {
    "US": ("USD", ["Kansas City, MO", "Wichita, KS", "Omaha, NE", "Des Moines, IA", "Tulsa, OK"]),
    "MX": ("MXN", ["Monterrey, NL", "Guadalajara, JA", "Hermosillo, SO"]),
    "DE": ("EUR", ["Hamburg", "Köln", "Bremen"]),
    "VN": ("VND", ["Ho Chi Minh City", "Da Nang", "Hanoi"]),
    "IN": ("INR", ["Pune", "Chennai", "Ahmedabad"]),
    "CA": ("CAD", ["Winnipeg, MB", "Toronto, ON"]),
}
OFFSHORE_BANK_COUNTRIES = ["HK", "AE", "LT", "CY", "SG"]
CATEGORIES = ["produce", "packaging", "spices", "freight", "facilities", "equipment"]
CLERKS = [f"ap-clerk-{i}" for i in range(1, 9)]
INSIDER_CLERKS = ["ap-clerk-7", "ap-clerk-4"]
_NAME_A = [
    "Prairie",
    "Heartland",
    "Sonora",
    "Rhein",
    "Mekong",
    "Deccan",
    "Great Plains",
    "Riverbend",
    "Summit",
    "Bluestem",
    "Cedar",
    "Northgate",
    "Lotus",
    "Saffron",
    "Ironwood",
    "Harbor",
    "Golden",
    "Maple",
]
_NAME_B = [
    "Packaging",
    "Produce",
    "Spices",
    "Logistics",
    "Ceramics",
    "Supply",
    "Foods",
    "Trading",
    "Freight",
    "Facility Services",
    "Textiles",
    "Equipment",
    "Growers",
    "Imports",
]
_NAME_C = ["Co.", "LLC", "GmbH", "S.A. de C.V.", "Pvt Ltd", "Ltd", "Inc."]
_STREETS = [
    "Main St",
    "Industrial Blvd",
    "Commerce Dr",
    "River Rd",
    "Market St",
    "Hafenstraße",
    "Calle Reforma",
]

ARCHETYPE_WEIGHTS = {
    "honest_regular": 0.50,
    "honest_new_small": 0.09,
    "honest_bank_change_ok": 0.05,
    "honest_seasonal_spike": 0.04,
    "honest_shared_address": 0.03,
    "ato_bec": 0.09,
    "insider": 0.10,
    "fake_vendor": 0.10,
}


@dataclass
class World:
    vendors: list[Vendor]
    invoices: list[Invoice]
    labels: dict[str, Labels]
    today: date
    seed: int
    archetypes: dict[str, str] = field(default_factory=dict)  # vendor_id -> archetype

    def vendor_map(self) -> dict[str, Vendor]:
        return {v.id: v for v in self.vendors}


class _Gen:
    def __init__(self, seed: int, today: date, approval_limit_cents: int):
        self.r = random.Random(seed)
        self.today = today
        self.limit = approval_limit_cents
        self.n_vendor = 0
        self.n_invoice = 0
        self.shared_park = f"{self.r.randint(100, 999)} Commerce Park Dr, Kansas City, MO"

    # -- identity pieces -----------------------------------------------------------------------------

    def tax_id(self, valid: bool = True) -> str:
        first8 = "".join(str(self.r.randint(0, 9)) for _ in range(8))
        tid = make_tax_id(first8)
        if not valid:
            last = int(tid[-1])
            tid = tid[:-1] + str((last + self.r.randint(1, 9)) % 10)
        return tid

    def phone(self, country: str, voip: bool = False) -> str:
        if voip:
            return f"{self.r.choice(VOIP_PREFIXES)}{self.r.randint(100, 999)}-{self.r.randint(1000, 9999)}"
        cc = {"US": "+1", "CA": "+1", "MX": "+52", "DE": "+49", "VN": "+84", "IN": "+91"}[country]
        return f"{cc}-{self.r.randint(200, 989)}-{self.r.randint(100, 999)}-{self.r.randint(1000, 9999)}"

    def address(self, country: str, virtual: bool = False) -> str:
        city = self.r.choice(COUNTRIES[country][1])
        if virtual:
            return self.r.choice(
                [
                    f"PO Box {self.r.randint(100, 99999)}, {city}",
                    f"Suite {self.r.randint(100, 900)} #{self.r.randint(1000, 9999)}, {city}",
                    f"PMB {self.r.randint(10, 999)}, {city}",
                ]
            )
        return f"{self.r.randint(10, 9999)} {self.r.choice(_STREETS)}, {city}"

    def bank(self, country: str) -> str:
        if country in ("DE",):
            return f"DE{self.r.randint(10, 99)}{self.r.randint(10**15, 10**16 - 1)}"
        return f"{country}{self.r.randint(10, 99)}{self.r.randint(10**9, 10**10 - 1)}"

    def name(self) -> str:
        return f"{self.r.choice(_NAME_A)} {self.r.choice(_NAME_B)} {self.r.choice(_NAME_C)}"

    def vendor_id(self) -> str:
        self.n_vendor += 1
        return f"v{self.n_vendor:05d}"

    def invoice_id(self) -> str:
        self.n_invoice += 1
        return f"i{self.n_invoice:06d}"

    def history(
        self, base: int, n: int, noise: float = 0.12, creep: float = 0.0, prefix: str = "INV"
    ) -> list[PastPayment]:
        out = []
        days = sorted(self.r.sample(range(15, 720), n), reverse=True) if n else []
        for k, d in enumerate(days):
            amt = int(base * (1 + creep) ** k * self.r.gauss(1, noise))
            out.append(
                PastPayment(
                    amount_cents=max(amt // 100 * 100 + self.r.choice([0, 0, 50, 99]), 5_000),
                    days_ago=d,
                    invoice_number=f"{prefix}-{self.r.randint(1000, 9999)}",
                )
            )
        return out

    def vendor(self, country: str | None = None, **kw) -> Vendor:
        country = country or self.r.choices(list(COUNTRIES), weights=[45, 15, 10, 10, 12, 8])[0]
        name = kw.pop("name", None) or self.name()
        domain = name.split()[0].lower() + name.split()[1].lower()[:4] + ".com"
        defaults = dict(
            id=self.vendor_id(),
            name=name,
            country=country,
            currency=COUNTRIES[country][0],
            category=self.r.choice(CATEGORIES),
            email=f"billing@{domain}",
            phone=self.phone(country),
            address=self.address(country),
            tax_id=self.tax_id(),
            bank_account=self.bank(country),
            bank_country=country,
            created_days_ago=self.r.randint(200, 2500),
            destination_tag=self.n_vendor,
        )
        defaults.update(kw)
        return Vendor(**defaults)

    def invoice(
        self,
        v: Vendor,
        amount: int,
        *,
        po: bool = True,
        delivery: bool = True,
        text: str = "",
        bank: str | None = None,
        remit_email: str | None = None,
        clerk: str | None = None,
        number: str | None = None,
        issue_ago: int | None = None,
    ) -> Invoice:
        issue = self.today - timedelta(days=issue_ago if issue_ago is not None else self.r.randint(0, 12))
        n_lines = self.r.randint(1, 3)
        parts = [amount // n_lines] * n_lines
        parts[-1] += amount - sum(parts)
        return Invoice(
            id=self.invoice_id(),
            vendor_id=v.id,
            vendor_name=v.name,
            invoice_number=number or f"INV-{self.r.randint(10000, 99999)}",
            amount_cents=amount,
            issue_date=issue,
            due_date=issue + timedelta(days=self.r.choice([15, 30, 30, 45])),
            po_number=f"PO-{self.r.randint(40000, 49999)}" if po else None,
            delivery_confirmed=delivery,
            bank_account=bank if bank is not None else v.bank_account,
            remit_email=remit_email or v.email,
            line_items=[
                LineItem(description=f"{v.category} lot {k + 1}", unit_cents=p) for k, p in enumerate(parts)
            ],
            submitted_by=clerk or self.r.choice(CLERKS),
            raw_text=text,
            source="synthetic",
        )


_URGENT = [
    "URGENT: please process today, our account is under audit.",
    "Final notice - payment overdue, wire immediately to avoid supply stop.",
    "Our bank details have changed. Please pay ASAP to the new account below.",
    "Confidential - CFO requested this be paid right away.",
]
_NORMAL = ["Thank you for your business.", "Net 30. Questions: reply to this email.", "", ""]


def generate_world(
    seed: int = 7, n_vendors: int = 600, today: date | None = None, approval_limit_cents: int = 500_000
) -> World:
    g = _Gen(seed, today or date(2026, 10, 10), approval_limit_cents)
    r = g.r
    vendors: list[Vendor] = []
    invoices: list[Invoice] = []
    labels: dict[str, Labels] = {}
    archetypes: dict[str, str] = {}
    fake_pool: list[Vendor] = []

    def add(inv: Invoice, cls: RiskClass, pattern: str, unusual: bool = False) -> None:
        invoices.append(inv)
        labels[inv.id] = Labels(risk_class=cls, pattern=pattern, honest_unusual=unusual)

    names, weights = zip(*ARCHETYPE_WEIGHTS.items(), strict=True)
    for _ in range(n_vendors):
        kind = r.choices(names, weights=weights)[0]
        base = int(r.lognormvariate(12.6, 0.8))  # ~ $3k median, cents
        base = min(max(base, 20_000), 4_000_000)

        if kind in (
            "honest_regular",
            "honest_seasonal_spike",
            "honest_shared_address",
            "honest_bank_change_ok",
        ):
            extra = {}
            if kind == "honest_shared_address":
                extra["address"] = g.shared_park
                extra["country"] = "US"
            if kind == "honest_bank_change_ok":
                extra["bank_changed_days_ago"] = r.randint(3, 60)
                extra["bank_change_confirmed_oob"] = True
            v = g.vendor(**extra)
            v.history = g.history(base, r.randint(4, 30))
            v.oob_verified = r.random() < 0.7
            if kind == "honest_bank_change_ok":
                v.previous_bank_account = g.bank(v.country)
            vendors.append(v)
            archetypes[v.id] = kind
            if r.random() < 0.06:  # small honest shops on VOIP lines / free email exist too
                v.phone = g.phone(v.country, voip=True)
            for _k in range(r.choice([1, 1, 2])):
                mult = r.uniform(2.0, 3.0) if kind == "honest_seasonal_spike" else r.gauss(1, 0.12)
                amt = max(int(base * mult) // 100 * 100, 5_000)
                # Overlap with bad-actor signals: honest "overdue" reminders, invoicing via a billing platform.
                text = r.choice(_URGENT[1:2]) if r.random() < 0.05 else r.choice(_NORMAL)
                remit = (
                    f"invoices@{r.choice(['billtrust-mail.com', 'quickpay-notify.com'])}"
                    if r.random() < 0.04
                    else None
                )
                add(
                    g.invoice(
                        v, amt, po=r.random() < 0.88, delivery=r.random() < 0.85, text=text, remit_email=remit
                    ),
                    RiskClass.HONEST,
                    kind,
                    unusual=kind != "honest_regular",
                )

        elif kind == "honest_new_small":
            v = g.vendor(created_days_ago=r.randint(3, 60))
            v.history = g.history(int(base * 0.3), r.randint(0, 2))
            v.oob_verified = r.random() < 0.5
            if r.random() < 0.3:
                v.email = f"{v.name.split()[0].lower()}.billing@gmail.com"  # tiny shops use free email
            vendors.append(v)
            archetypes[v.id] = kind
            amt = r.randint(15_000, 240_000) // 100 * 100
            add(
                g.invoice(v, amt, po=r.random() < 0.6, delivery=r.random() < 0.7, text=r.choice(_NORMAL)),
                RiskClass.HONEST,
                kind,
                unusual=True,
            )

        elif kind == "ato_bec":
            v = g.vendor()
            v.history = g.history(base, r.randint(6, 30))
            vendors.append(v)
            archetypes[v.id] = kind
            variant = r.random()
            attacker_bank = g.bank(r.choice([*OFFSHORE_BANK_COUNTRIES, v.country]))
            lookalike = v.email.replace(".com", r.choice(["-billing.com", ".co", "s.com", "-pay.net"]))
            amt = int(base * r.uniform(0.95, 1.6)) // 100 * 100
            if r.random() < 0.3:  # careful attackers skip the urgency and keep the real reply-to
                lookalike = v.email if variant < 0.6 else lookalike
            if variant < 0.6:  # invoice carries new bank details
                text = r.choice(_URGENT) if r.random() < 0.7 else r.choice(_NORMAL)
                inv = g.invoice(v, amt, bank=attacker_bank, remit_email=lookalike, text=text)
            else:  # attacker changed the master file via a hijacked contact
                v.previous_bank_account = v.bank_account
                v.bank_account = attacker_bank
                v.bank_country = attacker_bank[:2]
                v.bank_changed_days_ago = r.randint(0, 14)
                v.contact_changed_days_ago = r.randint(0, 20)
                v.email = lookalike
                inv = g.invoice(v, amt, text=r.choice(_URGENT + _NORMAL))
            add(inv, RiskClass.ATO_BEC, "bank_change_unconfirmed" if variant >= 0.6 else "invoice_bank_swap")

        elif kind == "insider":
            pattern = r.choice(["duplicate", "split", "creep", "no_po"])
            clerk = r.choice(INSIDER_CLERKS)
            v = g.vendor()
            creep = 0.09 if pattern == "creep" else 0.0
            v.history = g.history(base, r.randint(6, 25), creep=creep)
            vendors.append(v)
            archetypes[v.id] = f"insider_{pattern}"
            if pattern == "duplicate" and v.history:
                past = r.choice(v.history[-4:])
                number = past.invoice_number + r.choice(["A", "-1", "B", ""])
                inv = g.invoice(
                    v, past.amount_cents, number=number, clerk=clerk, po=r.random() < 0.3, delivery=False
                )
                add(inv, RiskClass.INSIDER, "duplicate")
            elif pattern == "split":
                parts = r.randint(2, 3)
                for _p in range(parts):
                    amt = r.randint(int(g.limit * 0.86), g.limit - 100) // 100 * 100
                    inv = g.invoice(
                        v, amt, clerk=clerk, po=False, delivery=r.random() < 0.3, issue_ago=r.randint(0, 5)
                    )
                    add(inv, RiskClass.INSIDER, "split")
            elif pattern == "creep":
                last = v.history[-1].amount_cents if v.history else base
                inv = g.invoice(
                    v,
                    int(last * r.uniform(1.08, 1.2)) // 100 * 100,
                    clerk=clerk,
                    po=r.random() < 0.4,
                    delivery=r.random() < 0.4,
                )
                add(inv, RiskClass.INSIDER, "creep")
            else:
                inv = g.invoice(
                    v, int(base * r.uniform(1.1, 2.2)) // 100 * 100, clerk=clerk, po=False, delivery=False
                )
                add(inv, RiskClass.INSIDER, "no_po_no_delivery")

        else:  # fake_vendor
            country = r.choice(["US", "US", "MX", "IN", "CA"])
            careful = (
                r.random() < 0.25
            )  # well-built synthetic identity: valid tax id, landline, street address
            v = g.vendor(
                country=country,
                created_days_ago=r.randint(2, 45) if not careful else r.randint(30, 240),
                tax_id=g.tax_id(valid=careful or r.random() < 0.3),
                phone=g.phone(country, voip=not careful and r.random() < 0.7),
                address=g.address(country, virtual=not careful and r.random() < 0.65),
            )
            if r.random() < 0.4:
                v.email = f"{v.name.split()[0].lower()}{r.randint(10, 99)}@{r.choice(['gmail.com', 'proton.me', 'outlook.com'])}"
            if fake_pool and r.random() < 0.7:  # join a ring: share 1-2 attributes with an existing fake
                anchor = r.choice(fake_pool)
                for attr in r.sample(["bank_account", "address", "phone", "tax_id"], k=r.choice([1, 1, 2])):
                    setattr(v, attr, getattr(anchor, attr))
            v.history = g.history(int(base * 0.8), r.randint(0, 3))
            vendors.append(v)
            fake_pool.append(v)
            archetypes[v.id] = "fake_vendor"
            amt = r.choice([r.randint(3, 15) * 100_000, int(base * r.uniform(0.8, 1.5)) // 100 * 100])
            add(
                g.invoice(
                    v,
                    amt,
                    po=r.random() < 0.25,
                    delivery=r.random() < 0.2,
                    text=r.choice(_NORMAL + _URGENT[:1]),
                ),
                RiskClass.FAKE_VENDOR,
                "fake_vendor",
            )

    return World(
        vendors=vendors, invoices=invoices, labels=labels, today=g.today, seed=seed, archetypes=archetypes
    )
