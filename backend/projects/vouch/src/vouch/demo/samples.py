"""Synthetic sample invoices for the demo: PDF, PNG (OCR), XLSX, CSV and email body.

``vouch-make-samples`` writes them to ``projects/vouch/samples/`` for manual uploads; the
scenario also builds them in memory with dates relative to today.
"""

from __future__ import annotations

import base64
import csv
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

from ..config import SAMPLES_DIR
from ..models import Attachment, IntakeRequest

# ----------------------------------------------------------------- renderers ----


def make_pdf(lines: list[str], title: str) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle(title)
    width, height = LETTER
    y = height - 72
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, y, lines[0])
    y -= 30
    c.setFont("Helvetica", 11)
    for ln in lines[1:]:
        if ln == "":
            y -= 8
            continue
        c.drawString(72, y, ln)
        y -= 16
        if y < 72:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 72
    c.save()
    return buf.getvalue()


def make_png(lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    except OSError:  # pragma: no cover - font layout differs per host
        font = ImageFont.load_default(size=34)
        bold = ImageFont.load_default(size=44)
    width = 1500
    height = 160 + 54 * len(lines)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    draw.text((80, y), lines[0], fill="black", font=bold)
    y += 90
    for ln in lines[1:]:
        draw.text((80, y), ln, fill="black", font=font)
        y += 54
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_xlsx(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


def make_eml(headers: dict[str, str], body: str, attachments: list[tuple[str, str, bytes]]) -> bytes:
    msg = EmailMessage()
    for k, v in headers.items():
        if k.lower() == "authentication-results":
            for part in v.split("\n"):
                msg[k] = part
        else:
            msg[k] = v
    msg.set_content(body)
    for filename, ctype, data in attachments:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


# ------------------------------------------------------------------ content ----


@dataclass
class Sample:
    key: str
    description: str
    request: IntakeRequest
    files: dict[str, bytes]  # filename → bytes (eml, pdf, …) for samples/
    received_offset: timedelta
    expected_status: str
    expected_risk: str


def _auth_pass(domain: str) -> str:
    return (
        f"mx.vouch.example; spf=pass (sender IP is authorized) smtp.mailfrom={domain}; "
        f"dkim=pass header.d={domain}; dmarc=pass (p=REJECT) header.from={domain}"
    )


def _att(filename: str, ctype: str, data: bytes) -> Attachment:
    import hashlib

    return Attachment(
        filename=filename,
        content_type=ctype,
        data_b64=base64.b64encode(data).decode(),
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )


def _headers(
    from_: str,
    subject: str,
    sent: datetime,
    domain: str,
    *,
    reply_to: str | None = None,
    auth: str | None = None,
    to: str = "payables@owner.example",
) -> dict[str, str]:
    h = {
        "From": from_,
        "To": to,
        "Subject": subject,
        "Date": format_datetime(sent),
        "Message-ID": f"<{abs(hash((from_, subject, sent.isoformat())))}@{domain}>",
        "Authentication-Results": auth if auth is not None else _auth_pass(domain),
    }
    if reply_to:
        h["Reply-To"] = reply_to
    return h


def build_samples(now: datetime | None = None) -> list[Sample]:
    now = now or datetime.now(UTC)
    today: date = now.date()
    fmt = lambda d: d.strftime("%Y-%m-%d")  # noqa: E731
    out: list[Sample] = []

    # 1 — Reyes Packaging: PDF attachment, everything matches.
    t = now - timedelta(days=2, hours=1)
    pdf = make_pdf(
        [
            "Reyes Packaging",
            "Av. Insurgentes Sur 1602, Mexico City",
            "Email: ar@reyespackaging.mx    Phone: +52 55 1234 5678",
            "RFC: RPA230214001",
            "",
            "INVOICE",
            "Invoice No: RP-10482",
            f"Invoice Date: {fmt(today - timedelta(days=2))}",
            f"Due Date: {fmt(today + timedelta(days=3))}",
            "PO Number: 7731",
            "",
            "Description: Corrugated shipping cartons, 12,000 units",
            "Subtotal: $6,400.00",
            "Total Due: $6,400.00 USD",
            "",
            "Bank: BBVA Mexico",
            "CLABE: 012180001234567891",
            "SWIFT: BCMRMXMMPYM",
        ],
        "Invoice RP-10482",
    )
    headers = _headers(
        "Reyes Packaging AR <ar@reyespackaging.mx>",
        "Invoice RP-10482 — cartons PO 7731",
        t,
        "reyespackaging.mx",
    )
    body = "Hola, attached is invoice RP-10482 for PO 7731. Same account as always. Gracias, Lucía"
    out.append(
        Sample(
            key="reyes",
            description="Known vendor, PDF attachment, authenticated sender",
            request=IntakeRequest(
                headers=headers,
                body_text=body,
                attachments=[_att("RP-10482.pdf", "application/pdf", pdf)],
                source="email",
            ),
            files={
                "01-reyes-RP-10482.eml": make_eml(headers, body, [("RP-10482.pdf", "application/pdf", pdf)]),
                "01-reyes-RP-10482.pdf": pdf,
            },
            received_offset=now - t,
            expected_status="vouched",
            expected_risk="none",
        )
    )

    # 2 — Warsaw Steel: email-body invoice from a lookalike domain with new bank details.
    t = now - timedelta(days=1, hours=2)
    body = "\n".join(
        [
            "Dear Accounts Payable,",
            "",
            "Please find below our invoice. NOTE: our banking details have changed, kindly remit to the new account.",
            "",
            "Warsaw Steel Sp. z o.o.",
            "ul. Hutnicza 12, 03-100 Warszawa",
            "NIP: 5252345678",
            "Invoice No: WS-2026-0917",
            f"Invoice Date: {fmt(today - timedelta(days=1))}",
            f"Due Date: {fmt(today + timedelta(days=4))}",
            "Description: Structural steel beams, lot 17",
            "Total Due: USD 12,000.00",
            "",
            "Bank Name: Commerzbank AG",
            "IBAN: DE89 3704 0044 0532 0130 00",
            "SWIFT: COBADEFFXXX",
            "",
            "Kind regards,",
            "Marta Kowalski",
            "Finance, Warsaw Steel",
        ]
    )
    headers = _headers(
        "Warsaw Steel Finance <finance.ws@warsawsteel-eu.com>",
        "Invoice WS-2026-0917 — updated bank details",
        t,
        "warsawsteel-eu.com",
        reply_to="ws.accounts.update@protonmail.com",
        auth="mx.vouch.example; spf=pass smtp.mailfrom=warsawsteel-eu.com; dkim=pass header.d=warsawsteel-eu.com; dmarc=none header.from=warsawsteel-eu.com",
    )
    out.append(
        Sample(
            key="warsaw",
            description="Known vendor, invoice in the email body, lookalike sender domain + new IBAN",
            request=IntakeRequest(headers=headers, body_text=body, source="email"),
            files={"02-warsaw-WS-2026-0917.eml": make_eml(headers, body, [])},
            received_offset=now - t,
            expected_status="verify",
            expected_risk="changed_bank",
        )
    )

    # 3 & 4 — Midwest Pallets: XLSX attachment, then the same email again 40 minutes later.
    t = now - timedelta(days=3, hours=3)
    xlsx = make_xlsx(
        [
            ["Midwest Pallets", ""],
            ["4100 Front St, Kansas City, MO 64120", ""],
            ["Email", "ap@midwestpallets.com"],
            ["EIN", "47-1234567"],
            ["Invoice Number", "MP-5521"],
            ["Invoice Date", fmt(today - timedelta(days=3))],
            ["Due Date", fmt(today + timedelta(days=2))],
            ["Item", "Qty", "Unit", "Amount"],
            ["48x40 GMA pallets", "550", "$9.00", "$4,950.00"],
            ["Total Due", "$4,950.00"],
            ["Account Number", "001234567890"],
            ["Routing Number", "101000019"],
        ]
    )
    headers = _headers("Midwest Pallets <ap@midwestpallets.com>", "Invoice MP-5521", t, "midwestpallets.com")
    body = "Monthly pallet order attached. Thanks, Tom"
    out.append(
        Sample(
            key="midwest",
            description="Known vendor, Excel attachment, regular monthly amount",
            request=IntakeRequest(
                headers=headers,
                body_text=body,
                attachments=[
                    _att(
                        "MP-5521.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        xlsx,
                    )
                ],
                source="email",
            ),
            files={
                "03-midwest-MP-5521.eml": make_eml(
                    headers,
                    body,
                    [
                        (
                            "MP-5521.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            xlsx,
                        )
                    ],
                ),
                "03-midwest-MP-5521.xlsx": xlsx,
            },
            received_offset=now - t,
            expected_status="vouched",
            expected_risk="none",
        )
    )
    t2 = t + timedelta(minutes=40)
    headers2 = _headers(
        "Midwest Pallets <ap@midwestpallets.com>", "Re: Invoice MP-5521", t2, "midwestpallets.com"
    )
    body2 = "Resending in case the first one did not come through. Tom"
    out.append(
        Sample(
            key="midwest-dup",
            description="Same Excel invoice re-sent 40 minutes later (duplicate)",
            request=IntakeRequest(
                headers=headers2,
                body_text=body2,
                attachments=[
                    _att(
                        "MP-5521.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        xlsx,
                    )
                ],
                source="email",
            ),
            files={
                "04-midwest-MP-5521-resend.eml": make_eml(
                    headers2,
                    body2,
                    [
                        (
                            "MP-5521.xlsx",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            xlsx,
                        )
                    ],
                )
            },
            received_offset=now - t2,
            expected_status="quick_check",
            expected_risk="duplicate_or_split",
        )
    )

    # 5 & 6 — Brightline Supply: two CSV invoices just under the limit, 4 minutes apart.
    t = now - timedelta(days=1, hours=0, minutes=10)
    for n, (inv, minutes) in enumerate([("BL-3307", 0), ("BL-3308", 4)]):
        rows = [
            ["Brightline Supply", ""],
            ["7300 W 110th St, Overland Park, KS 66210", ""],
            ["Email", "billing@brightlinesupply.com"],
            ["Invoice Number", inv],
            ["Invoice Date", fmt(today - timedelta(days=1))],
            ["Due Date", fmt(today + timedelta(days=5))],
            [
                "Description",
                "Janitorial supplies, half order" if n == 0 else "Janitorial supplies, second half",
            ],
            ["Total Due", "$4,900.00"],
            ["Account Number", "44556677889"],
            ["Routing Number", "101089742"],
        ]
        data = make_csv(rows)
        ts = t + timedelta(minutes=minutes)
        headers = _headers(
            "Brightline Supply <billing@brightlinesupply.com>", f"Invoice {inv}", ts, "brightlinesupply.com"
        )
        body = f"Invoice {inv} attached."
        out.append(
            Sample(
                key=f"brightline-{inv.lower()}",
                description=f"CSV invoice {inv}, one of two just under the approval limit",
                request=IntakeRequest(
                    headers=headers,
                    body_text=body,
                    attachments=[_att(f"{inv}.csv", "text/csv", data)],
                    source="email",
                ),
                files={
                    f"0{5 + n}-brightline-{inv}.eml": make_eml(
                        headers, body, [(f"{inv}.csv", "text/csv", data)]
                    ),
                    f"0{5 + n}-brightline-{inv}.csv": data,
                },
                received_offset=now - ts,
                expected_status="quick_check",
                expected_risk="duplicate_or_split",
            )
        )

    # 7 — Nova Trade LLC: uploaded PNG scan (OCR), new vendor sharing bank/phone/address.
    t = now - timedelta(days=1, hours=-2)
    png = make_png(
        [
            "Nova Trade LLC",
            "1201 N Orange St, Suite 600, Wilmington, DE 19801",
            "Phone: (816) 555-0192   Email: billing@novatrade-llc.com",
            "",
            "INVOICE",
            "Invoice No: NT-0001",
            f"Invoice Date: {fmt(today - timedelta(days=1))}",
            f"Due Date: {fmt(today + timedelta(days=6))}",
            "Description: Consulting services",
            "Total Due: $7,200.00",
            "",
            "Bank Name: First Keystone Bank",
            "Account Number: 998877664471",
            "Routing Number: 021000021",
        ]
    )
    out.append(
        Sample(
            key="nova",
            description="Uploaded image invoice (OCR), new vendor sharing bank account, phone and address with two other vendors",
            request=IntakeRequest(attachments=[_att("NT-0001.png", "image/png", png)], source="upload"),
            files={"07-nova-NT-0001.png": png},
            received_offset=now - t,
            expected_status="verify",
            expected_risk="unrecognized_vendor",
        )
    )

    # 8 — Café Santa Rita: uploaded PDF, new small vendor, verified.
    t = now - timedelta(days=1, hours=-1)
    pdf = make_pdf(
        [
            "Café Santa Rita",
            "Rua da Bahia 1148, Belo Horizonte, MG, Brazil",
            "CNPJ: 12.345.678/0001-95",
            "Email: vendas@cafesantarita.com.br   Phone: +55 31 3333 4444",
            "",
            "INVOICE",
            "Invoice No: CSR-0001",
            f"Invoice Date: {fmt(today - timedelta(days=1))}",
            f"Due Date: {fmt(today)}",
            "Description: 120 kg specialty coffee beans, lot BH-22",
            "Total Due: USD 1,850.00",
            "",
            "Bank Name: Banco do Brasil",
            "Account Number: 0011234567890",
            "SWIFT: BRASBRRJBHE",
        ],
        "Invoice CSR-0001",
    )
    out.append(
        Sample(
            key="santa-rita",
            description="Uploaded PDF, new small vendor with verified registration and bank",
            request=IntakeRequest(
                attachments=[_att("CSR-0001.pdf", "application/pdf", pdf)], source="upload"
            ),
            files={"08-santa-rita-CSR-0001.pdf": pdf},
            received_offset=now - t,
            expected_status="vouched",
            expected_risk="none",
        )
    )
    return out


def write_samples(directory=SAMPLES_DIR) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for s in build_samples():
        for name, data in s.files.items():
            (directory / name).write_bytes(data)
            written.append(name)
    readme = directory / "README.md"
    readme.write_text(
        "# Synthetic sample invoices\n\n"
        "Generated by `vouch-make-samples` (`make samples`). Every company, person, account and tax id is invented.\n\n"
        "| File | Format | Scenario |\n|---|---|---|\n"
        + "\n".join(
            f"| {name} | {name.rsplit('.', 1)[-1]} | {s.description} |"
            for s in build_samples()
            for name in s.files
        )
        + "\n\nUpload any of them with `POST /v1/intake/upload` or post an `.eml` to `POST /v1/intake/email`.\n",
        encoding="utf-8",
    )
    return written


def main() -> None:
    for name in write_samples():
        print("wrote", SAMPLES_DIR / name)
