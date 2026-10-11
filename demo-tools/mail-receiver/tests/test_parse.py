"""Parsing: header preservation, intake shape, attachment allowlist and filename safety."""

from __future__ import annotations

import base64
import hashlib
from email.message import EmailMessage

from mail_receiver.parse import check_attachment, parse_message, safe_filename, sniff_matches

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.4\n%demo\n" + b"0" * 64
XLSX = b"PK\x03\x04" + b"\x00" * 64

AUTH = (
    "mx.vouch.local (demo-simulated); spf=pass smtp.mailfrom=reyespackaging.mx; "
    "dkim=pass header.d=reyespackaging.mx; dmarc=pass header.from=reyespackaging.mx"
)
RECEIVED_1 = (
    "from mail.reyespackaging.mx (mail.reyespackaging.mx [203.0.113.10]) by mx.vouch.local with ESMTPS id abc"
)
RECEIVED_2 = "from relay.example (relay.example [203.0.113.11]) by mail.reyespackaging.mx with ESMTP id def"


def _message(*, attachments: list[tuple[str, str, bytes]] = (), html: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["Received"] = RECEIVED_1
    msg["Received"] = RECEIVED_2
    msg["Authentication-Results"] = AUTH
    msg["From"] = "Reyes Packaging AR <ar@reyespackaging.mx>"
    msg["To"] = "business@vouch.local"
    msg["Reply-To"] = "lucia@reyespackaging.mx"
    msg["Subject"] = "Invoice RP-10517"
    msg["Message-ID"] = "<abc@reyespackaging.mx>"
    msg.set_content("Hola, attached is invoice RP-10517.\n")
    if html:
        msg.add_alternative(html, subtype="html")
    for filename, ctype, data in attachments:
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def test_headers_are_kept_verbatim_including_repeated_received():
    parsed = parse_message(_message())
    headers = parsed.intake["headers"]
    assert headers["Authentication-Results"] == AUTH
    assert headers["Received"] == f"{RECEIVED_1}\n{RECEIVED_2}"  # joined like the backend's parse_eml
    assert parsed.authentication_results == [AUTH]
    assert parsed.received == [RECEIVED_1, RECEIVED_2]
    assert headers["From"] == "Reyes Packaging AR <ar@reyespackaging.mx>"
    assert parsed.from_addr == "ar@reyespackaging.mx"
    assert parsed.from_name == "Reyes Packaging AR"
    assert parsed.reply_to == "lucia@reyespackaging.mx"
    assert parsed.message_id == "<abc@reyespackaging.mx>"


def test_intake_shape_matches_backend_intake_request():
    parsed = parse_message(_message(attachments=[("RP-10517.pdf", "application/pdf", PDF)]))
    intake = parsed.intake
    assert set(intake) == {"headers", "body_text", "body_html", "attachments", "source", "received_at"}
    assert intake["source"] == "email"
    assert intake["received_at"].endswith("Z")
    assert intake["body_text"].startswith("Hola, attached is invoice RP-10517.")
    assert intake["body_html"] == ""
    (att,) = intake["attachments"]
    assert set(att) == {"filename", "content_type", "data_b64", "sha256", "size"}
    assert att["filename"] == "RP-10517.pdf"
    assert att["content_type"] == "application/pdf"
    assert base64.b64decode(att["data_b64"]) == PDF
    assert att["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert att["size"] == len(PDF)


def test_html_alternative_is_captured_not_treated_as_attachment():
    parsed = parse_message(_message(html="<p>Invoice <b>RP-10517</b></p>"))
    assert parsed.intake["body_html"].startswith("<p>Invoice")
    assert parsed.intake["attachments"] == []
    assert parsed.attachments == []


def test_allowlist_by_extension_and_content():
    raw = _message(
        attachments=[
            ("invoice.exe", "application/octet-stream", b"MZ\x90\x00binary"),
            ("page.html", "text/html", b"<script>alert(1)</script>"),
            ("fake.pdf", "application/pdf", b"this is not a pdf"),
            ("scan.png", "image/png", PNG),
            ("photo.jpg", "image/jpeg", JPG),
            ("sheet.xlsx", "application/octet-stream", XLSX),  # declared type is not trusted
            ("rows.csv", "text/csv", b"a,b\n1,2\n"),
            ("note.txt", "text/plain", b"plain text"),
            ("binary.csv", "text/csv", b"a,b\n\x00\x01\x02"),
        ]
    )
    parsed = parse_message(raw)
    verdict = {a.filename: (a.kept, a.reason) for a in parsed.attachments}
    assert verdict["invoice.exe"] == (False, "extension .exe not in allowlist")
    assert verdict["page.html"] == (False, "extension .html not in allowlist")
    assert verdict["fake.pdf"] == (False, "content does not look like .pdf")
    assert verdict["binary.csv"] == (False, "content does not look like .csv")
    for name in ("scan.png", "photo.jpg", "sheet.xlsx", "rows.csv", "note.txt"):
        assert verdict[name] == (True, ""), name
    kept = {a["filename"]: a["content_type"] for a in parsed.intake["attachments"]}
    assert kept == {
        "scan.png": "image/png",
        "photo.jpg": "image/jpeg",
        "sheet.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "rows.csv": "text/csv",
        "note.txt": "text/plain",
    }
    assert len(parsed.warnings) == 4


def test_attachment_size_and_count_limits():
    big = PDF + b"x" * 5000
    info = check_attachment("big.pdf", "application/pdf", big, max_attachment_bytes=1000)
    assert not info.kept and "larger than 1000" in info.reason
    assert check_attachment("empty.pdf", "application/pdf", b"").reason == "empty attachment"
    raw = _message(attachments=[(f"f{i}.csv", "text/csv", b"a,b\n") for i in range(5)])
    parsed = parse_message(raw, max_attachments=3)
    assert sum(a.kept for a in parsed.attachments) == 3
    assert [a.reason for a in parsed.attachments if not a.kept] == ["more than 3 attachments"] * 2


def test_safe_filename_blocks_path_traversal_and_odd_characters():
    assert safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_filename("..\\..\\windows\\system32\\x.csv") == "x.csv"
    assert safe_filename("inv oice (final) #2.xlsx") == "inv-oice-final-2.xlsx"
    assert safe_filename("") == "attachment"
    assert safe_filename("..") == "attachment"
    assert len(safe_filename("a" * 500 + ".pdf")) <= 120


def test_kept_payloads_are_stored_under_safe_unique_names():
    raw = _message(
        attachments=[
            ("../../etc/passwd.pdf", "application/pdf", PDF),
            ("passwd.pdf", "application/pdf", PDF + b"2"),
        ]
    )
    parsed = parse_message(raw)
    assert set(parsed.kept_payloads) == {"passwd.pdf", "passwd-2.pdf"}
    # the original filename stays in the intake JSON: it is data for the backend, not a path
    assert [a["filename"] for a in parsed.intake["attachments"]] == ["../../etc/passwd.pdf", "passwd.pdf"]


def test_sniff_matches_each_allowed_type():
    assert sniff_matches("pdf", PDF) and not sniff_matches("pdf", PNG)
    assert sniff_matches("png", PNG) and not sniff_matches("png", JPG)
    assert sniff_matches("jpg", JPG) and sniff_matches("jpeg", JPG)
    assert sniff_matches("xlsx", XLSX) and not sniff_matches("xlsx", PDF)
    assert sniff_matches("csv", "é,ü\n".encode()) and sniff_matches("txt", b"hello")
    assert not sniff_matches("exe", b"MZ")
