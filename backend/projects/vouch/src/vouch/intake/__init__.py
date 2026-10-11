"""Email/file intake: .eml and JSON envelopes, deterministic PDF/OCR/XLSX/CSV extraction, identity claims.

Structuring of the extracted text (amounts, dates, bank details) is the kernel's job
(`vouch.kernel.parse_invoice_text`) with the intake agent only pointing at verbatim quotes.
"""

from .claims import extract_claim
from .email_parse import envelope_from_headers, intake_body_text, parse_eml
from .extract import combine_documents, extract_file, normalize_text, ocr_backend, ocr_status

__all__ = [
    "combine_documents",
    "envelope_from_headers",
    "extract_claim",
    "extract_file",
    "intake_body_text",
    "normalize_text",
    "ocr_backend",
    "ocr_status",
    "parse_eml",
]
