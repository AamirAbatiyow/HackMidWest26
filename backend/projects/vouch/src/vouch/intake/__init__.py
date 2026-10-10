"""Email/file intake: deterministic extraction, then structuring with provenance checks."""

from .amounts import AmountParseError, format_cents, parse_amount_cents, parse_date
from .email_parse import envelope_from_headers, intake_body_text, parse_eml
from .extract import combine_documents, extract_file, normalize_text, ocr_backend
from .structure import mask_account, parse_fields, provenance_check, regex_structure

__all__ = [
    "AmountParseError",
    "combine_documents",
    "envelope_from_headers",
    "extract_file",
    "format_cents",
    "intake_body_text",
    "mask_account",
    "normalize_text",
    "ocr_backend",
    "parse_amount_cents",
    "parse_date",
    "parse_eml",
    "parse_fields",
    "provenance_check",
    "regex_structure",
]
