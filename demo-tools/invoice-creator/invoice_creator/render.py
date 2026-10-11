"""Render an Invoice as PDF, PNG, XLSX, CSV or plain text.

Every format carries the same label/value vocabulary ("Invoice No:", "Due Date:", "Total Due:",
"IBAN:", …) so the backend's deterministic extractors find the fields regardless of format.
Each document carries a small "DEMO — synthetic data" footer.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass

from .models import Invoice, OutputFormat

DEMO_FOOTER = "DEMO — synthetic data (Vouch demo-tools)"

CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}

_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


@dataclass
class Rendered:
    filename: str
    content_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def size(self) -> int:
        return len(self.data)


# ------------------------------------------------------------------ helpers ----


def money(amount: float, currency: str = "USD", *, with_code: bool = False) -> str:
    if currency == "USD":
        s = f"${amount:,.2f}"
        return f"{s} USD" if with_code else s
    return f"{currency} {amount:,.2f}"


def qty_text(q: float) -> str:
    return f"{int(q):,}" if float(q).is_integer() else f"{q:,.2f}"


def safe_filename(stem: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "invoice"
    stem = re.sub(r"\.{2,}", ".", stem).replace("-.", "-").replace(".-", "-")
    return f"{stem}.{ext}"


# Labels the backend's deterministic parser recognises for the account field
# (``iban`` / ``account no|number|#`` / ``acct``). Anything else (CLABE, Sort Code, …) is printed as
# a canonical "Bank account:" line with the local name alongside, so the number is always extracted.
_PARSEABLE_ACCOUNT_LABELS = {
    "iban", "account number", "account no", "account no.", "account #", "acct", "acct.",
}


def account_line(inv: Invoice) -> tuple[str, str] | None:
    """``(label, value)`` for the account line, or None when the invoice has no account."""
    if not inv.bank.account_number:
        return None
    label = inv.bank.account_label.strip()
    if label.lower() in _PARSEABLE_ACCOUNT_LABELS:
        return label, inv.bank.account_number
    return "Bank account", f"{inv.bank.account_number}  ({label})"


def invoice_lines(inv: Invoice, owner_name: str = "", owner_address: str = "") -> list[str]:
    """Canonical plain-text form of the invoice (email body, PNG and the PDF are built from it).
    The ``From:`` line and the label vocabulary below are what the backend's parser keys on."""
    lines: list[str] = [inv.vendor_name, f"From: {inv.vendor_name}"]
    if inv.remit_to.address:
        lines.append(inv.remit_to.address)
    contact = []
    if inv.vendor_email:
        contact.append(f"Email: {inv.vendor_email}")
    if inv.remit_to.phone:
        contact.append(f"Phone: {inv.remit_to.phone}")
    if contact:
        lines.append("    ".join(contact))
    if inv.remit_to.tax_id:
        lines.append(f"{inv.remit_to.tax_id_label}: {inv.remit_to.tax_id}")
    lines += [
        "",
        "INVOICE",
        f"Invoice No: {inv.invoice_number}",
        f"Invoice Date: {inv.invoice_date.isoformat()}",
        f"Due Date: {inv.due_date.isoformat()}",
    ]
    if inv.po_number:
        lines.append(f"PO Number: {inv.po_number}")
    if owner_name:
        bill_to = owner_name if not owner_address else f"{owner_name}, {owner_address}"
        lines.append(f"Bill To: {bill_to}")
    if inv.description:
        lines.append(f"Description: {inv.description}")
    if inv.line_items:
        lines.append("")
        for li in inv.line_items:
            lines.append(
                f"{li.description} — {qty_text(li.quantity)} x {money(li.unit_price, inv.currency)}"
                f" = {money(li.amount, inv.currency)}"
            )
    subtotal = inv.line_total if inv.line_items else inv.amount
    lines += [
        "",
        f"Subtotal: {money(subtotal, inv.currency)}",
        f"Total Due: {money(inv.amount, inv.currency, with_code=True)}",
        "",
        "Payment Details",
    ]
    if inv.bank.bank_name:
        lines.append(f"Bank Name: {inv.bank.bank_name}")
    if acct := account_line(inv):
        lines.append(f"{acct[0]}: {acct[1]}")
    if inv.bank.routing_number:
        lines.append(f"{inv.bank.routing_label}: {inv.bank.routing_number}")
    if inv.remit_to.contact_name:
        lines.append(f"Contact: {inv.remit_to.contact_name}")
    if inv.notes.strip():
        lines += ["", f"Notes: {inv.notes.strip()}"]
    return lines


def invoice_rows(inv: Invoice, owner_name: str = "", owner_address: str = "") -> list[list[str]]:
    """Tabular form used for XLSX and CSV. Two-cell rows read as ``Label: value`` downstream."""
    rows: list[list[str]] = [[inv.vendor_name, ""], ["From", inv.vendor_name]]
    if inv.remit_to.address:
        rows.append([inv.remit_to.address, ""])
    if inv.vendor_email:
        rows.append(["Email", inv.vendor_email])
    if inv.remit_to.phone:
        rows.append(["Phone", inv.remit_to.phone])
    if inv.remit_to.tax_id:
        rows.append([inv.remit_to.tax_id_label, inv.remit_to.tax_id])
    rows += [
        ["Invoice Number", inv.invoice_number],
        ["Invoice Date", inv.invoice_date.isoformat()],
        ["Due Date", inv.due_date.isoformat()],
    ]
    if inv.po_number:
        rows.append(["PO Number", inv.po_number])
    if owner_name:
        rows.append(["Bill To", f"{owner_name}, {owner_address}" if owner_address else owner_name])
    if inv.description:
        rows.append(["Description", inv.description])
    if inv.line_items:
        rows.append(["Item", "Qty", "Unit Price", "Amount"])
        for li in inv.line_items:
            rows.append(
                [
                    li.description,
                    qty_text(li.quantity),
                    money(li.unit_price, inv.currency),
                    money(li.amount, inv.currency),
                ]
            )
    subtotal = inv.line_total if inv.line_items else inv.amount
    rows += [
        ["Subtotal", money(subtotal, inv.currency)],
        ["Total Due", money(inv.amount, inv.currency, with_code=True)],
    ]
    if inv.bank.bank_name:
        rows.append(["Bank Name", inv.bank.bank_name])
    if acct := account_line(inv):
        rows.append(list(acct))
    if inv.bank.routing_number:
        rows.append([inv.bank.routing_label, inv.bank.routing_number])
    if inv.remit_to.contact_name:
        rows.append(["Contact", inv.remit_to.contact_name])
    if inv.notes.strip():
        rows.append(["Notes", inv.notes.strip()])
    rows.append([DEMO_FOOTER, ""])
    return rows


# ---------------------------------------------------------------------- PDF ----


def render_pdf(inv: Invoice, owner_name: str = "", owner_address: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    regular, bold = "Helvetica", "Helvetica-Bold"
    try:  # DejaVu covers accented vendor names (Café, Lucía); Helvetica lacks some glyphs.
        if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", f"{_FONT_DIR}/DejaVuSans.ttf"))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", f"{_FONT_DIR}/DejaVuSans-Bold.ttf"))
        regular, bold = "DejaVuSans", "DejaVuSans-Bold"
    except Exception:  # pragma: no cover - font availability differs per host
        pass

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle(f"Invoice {inv.invoice_number} — {inv.vendor_name}")
    c.setAuthor(inv.vendor_name)
    width, height = LETTER
    left, right = 54, width - 54
    y = height - 64

    def line(text: str, size: int = 10, font: str | None = None, color=colors.black, dy: int = 15) -> None:
        nonlocal y
        if y < 90:
            c.showPage()
            y = height - 64
        c.setFillColor(color)
        c.setFont(font or regular, size)
        c.drawString(left, y, text)
        y -= dy

    def rule(dy: int = 12) -> None:
        nonlocal y
        c.setStrokeColor(colors.HexColor("#b8b8b8"))
        c.setLineWidth(0.6)
        c.line(left, y + 4, right, y + 4)
        y -= dy

    # Accent bar + vendor block
    c.setFillColor(colors.HexColor("#1f3a5f"))
    c.rect(0, height - 18, width, 18, stroke=0, fill=1)
    line(inv.vendor_name, 20, bold, colors.HexColor("#1f3a5f"), dy=24)
    line(f"From: {inv.vendor_name}", 10, color=colors.HexColor("#444444"), dy=14)
    if inv.remit_to.address:
        line(inv.remit_to.address, 10, dy=14)
    contact = []
    if inv.vendor_email:
        contact.append(f"Email: {inv.vendor_email}")
    if inv.remit_to.phone:
        contact.append(f"Phone: {inv.remit_to.phone}")
    if contact:
        line("    ".join(contact), 10, dy=14)
    if inv.remit_to.tax_id:
        line(f"{inv.remit_to.tax_id_label}: {inv.remit_to.tax_id}", 10, dy=14)
    y -= 6
    rule()

    line("INVOICE", 16, bold, colors.HexColor("#444444"), dy=22)
    line(f"Invoice No: {inv.invoice_number}", 11, bold)
    line(f"Invoice Date: {inv.invoice_date.isoformat()}")
    line(f"Due Date: {inv.due_date.isoformat()}", 10, bold)
    if inv.po_number:
        line(f"PO Number: {inv.po_number}")
    if owner_name:
        bill_to = owner_name if not owner_address else f"{owner_name}, {owner_address}"
        line(f"Bill To: {bill_to}")
    if inv.description:
        line(f"Description: {inv.description}")
    y -= 4
    rule()

    if inv.line_items:
        # Table header with a light fill; columns right-aligned for numbers.
        c.setFillColor(colors.HexColor("#eef2f7"))
        c.rect(left, y - 4, right - left, 17, stroke=0, fill=1)
        c.setFillColor(colors.black)
        c.setFont(bold, 10)
        c.drawString(left + 4, y, "Item")
        c.drawRightString(right - 230, y, "Qty")
        c.drawRightString(right - 120, y, "Unit Price")
        c.drawRightString(right - 4, y, "Amount")
        y -= 19
        c.setFont(regular, 10)
        for li in inv.line_items:
            if y < 90:
                c.showPage()
                y = height - 64
                c.setFont(regular, 10)
            c.drawString(left + 4, y, li.description[:70])
            c.drawRightString(right - 230, y, qty_text(li.quantity))
            c.drawRightString(right - 120, y, money(li.unit_price, inv.currency))
            c.drawRightString(right - 4, y, money(li.amount, inv.currency))
            y -= 15
        y -= 4
        rule()

    subtotal = inv.line_total if inv.line_items else inv.amount
    line(f"Subtotal: {money(subtotal, inv.currency)}")
    line(f"Total Due: {money(inv.amount, inv.currency, with_code=True)}", 13, bold, dy=20)
    rule()

    line("Payment Details", 11, bold, colors.HexColor("#444444"), dy=17)
    if inv.bank.bank_name:
        line(f"Bank Name: {inv.bank.bank_name}")
    if acct := account_line(inv):
        line(f"{acct[0]}: {acct[1]}")
    if inv.bank.routing_number:
        line(f"{inv.bank.routing_label}: {inv.bank.routing_number}")
    if inv.remit_to.contact_name:
        line(f"Contact: {inv.remit_to.contact_name}")
    if inv.notes.strip():
        y -= 6
        notes = inv.notes.strip()
        words, cur = notes.split(), "Notes:"
        for w in words:
            if c.stringWidth(cur + " " + w, regular, 10) > right - left:
                line(cur)
                cur = w
            else:
                cur = f"{cur} {w}"
        line(cur)

    c.setFillColor(colors.HexColor("#8a8a8a"))
    c.setFont(regular, 8)
    c.drawString(left, 40, DEMO_FOOTER)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------- PNG ----


def render_png(inv: Invoice, owner_name: str = "", owner_address: str = "") -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(f"{_FONT_DIR}/DejaVuSans.ttf", 34)
        bold = ImageFont.truetype(f"{_FONT_DIR}/DejaVuSans-Bold.ttf", 46)
        small = ImageFont.truetype(f"{_FONT_DIR}/DejaVuSans.ttf", 22)
    except OSError:  # pragma: no cover - font layout differs per host
        font = ImageFont.load_default(size=34)
        bold = ImageFont.load_default(size=46)
        small = ImageFont.load_default(size=22)

    lines = invoice_lines(inv, owner_name, owner_address)
    width = 1600
    height = 220 + 54 * len(lines) + 70
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 22], fill=(31, 58, 95))
    y = 70
    draw.text((90, y), lines[0], fill="black", font=bold)
    y += 100
    for ln in lines[1:]:
        if ln == "INVOICE" or ln == "Payment Details":
            draw.line([(90, y - 10), (width - 90, y - 10)], fill=(180, 180, 180), width=2)
            draw.text((90, y), ln, fill=(40, 40, 40), font=bold)
            y += 64
            continue
        if ln.startswith("Total Due:"):
            draw.text((90, y), ln, fill="black", font=bold)
            y += 64
            continue
        draw.text((90, y), ln, fill="black", font=font)
        y += 54
    draw.text((90, height - 44), DEMO_FOOTER, fill=(130, 130, 130), font=small)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------- XLSX / CSV ----


def render_xlsx(inv: Invoice, owner_name: str = "", owner_address: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoice"
    for r in invoice_rows(inv, owner_name, owner_address):
        ws.append(r)
    ws["A1"].font = Font(bold=True, size=14)
    for row in ws.iter_rows():
        if row[0].value in ("Total Due", "Invoice Number"):
            for cell in row:
                cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 14
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_csv(inv: Invoice, owner_name: str = "", owner_address: str = "") -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(invoice_rows(inv, owner_name, owner_address))
    return buf.getvalue().encode("utf-8")


def render_text(inv: Invoice, owner_name: str = "", owner_address: str = "") -> str:
    return "\n".join(invoice_lines(inv, owner_name, owner_address) + ["", DEMO_FOOTER])


# -------------------------------------------------------------------- facade ----


def render(inv: Invoice, fmt: OutputFormat, owner_name: str = "", owner_address: str = "") -> Rendered | None:
    """Return the attachment for ``fmt`` or None for the body-only format."""
    if fmt == "body":
        return None
    if fmt == "pdf":
        data = render_pdf(inv, owner_name, owner_address)
    elif fmt == "png":
        data = render_png(inv, owner_name, owner_address)
    elif fmt == "xlsx":
        data = render_xlsx(inv, owner_name, owner_address)
    elif fmt == "csv":
        data = render_csv(inv, owner_name, owner_address)
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"unknown format {fmt!r}")
    return Rendered(
        filename=safe_filename(inv.invoice_number, fmt), content_type=CONTENT_TYPES[fmt], data=data
    )
