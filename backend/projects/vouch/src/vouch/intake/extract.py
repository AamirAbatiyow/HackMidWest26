"""Deterministic text/table extraction from invoice files.

PDF → pypdf (text) + pdfplumber (tables); images → Tesseract via pytesseract, falling back to
RapidOCR when the binary is missing; Excel → openpyxl; CSV → csv; text/email body as-is.
No model is involved here; the output feeds the structuring step.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import shutil
from functools import lru_cache
from pathlib import Path

from ..contracts import ExtractedDocument, ExtractedTable

log = logging.getLogger(__name__)

PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff", "image/bmp"}
XLSX_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
CSV_TYPES = {"text/csv", "application/csv"}
TEXT_TYPES = {"text/plain", "text/markdown"}

_EXT_KIND = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".tif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".csv": "csv",
    ".txt": "text",
    ".md": "text",
    ".eml": "text",
}


def detect_kind(filename: str, content_type: str | None = None, data: bytes | None = None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in PDF_TYPES:
        return "pdf"
    if ct in IMAGE_TYPES:
        return "image"
    if ct in XLSX_TYPES:
        return "xlsx"
    if ct in CSV_TYPES:
        return "csv"
    ext = Path(filename or "").suffix.lower()
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    if ct in TEXT_TYPES:
        return "text"
    if data:
        if data.startswith(b"%PDF"):
            return "pdf"
        if data.startswith(b"\x89PNG") or data[:3] == b"\xff\xd8\xff":
            return "image"
        if data.startswith(b"PK\x03\x04"):
            return "xlsx"
    return "unknown"


# ------------------------------------------------------------------ PDF ----


def extract_pdf(data: bytes, filename: str) -> ExtractedDocument:
    warnings: list[str] = []
    text_parts: list[str] = []
    tables: list[ExtractedTable] = []
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        for i, page in enumerate(reader.pages):
            text_parts.append(page.extract_text() or "")
            if i >= 20:
                warnings.append("only the first 20 pages were read")
                break
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"pypdf failed: {exc}")
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages[:20]):
                for t in page.extract_tables() or []:
                    rows = [[(c or "").strip() for c in row] for row in t if row]
                    if rows:
                        tables.append(ExtractedTable(source=f"{filename}#page{i + 1}", rows=rows))
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"pdfplumber tables failed: {exc}")
    text = "\n".join(p for p in text_parts if p).strip()
    if not text:
        warnings.append("no text layer found (scanned PDF?)")
    return ExtractedDocument(
        filename=filename,
        kind="pdf",
        text=text,
        tables=tables,
        extractor="pypdf+pdfplumber",
        warnings=warnings,
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------- image ----


@lru_cache(maxsize=1)
def ocr_backend() -> str:
    """Which OCR engine is available: 'tesseract', 'rapidocr' or 'none'."""
    try:
        import pytesseract  # noqa: F401

        if shutil.which("tesseract"):
            return "tesseract"
    except Exception:  # pragma: no cover
        pass
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return "rapidocr"
    except Exception:
        return "none"


def _prep_image(data: bytes):
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 1200:
        scale = 1200 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return img


def extract_image(data: bytes, filename: str) -> ExtractedDocument:
    backend = ocr_backend()
    warnings: list[str] = []
    text = ""
    if backend == "tesseract":
        import pytesseract

        text = pytesseract.image_to_string(_prep_image(data), config="--psm 6")
    elif backend == "rapidocr":
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        img = _prep_image(data).convert("RGB")
        result, _ = RapidOCR()(np.array(img))
        lines = [r[1] for r in (result or [])]
        text = "\n".join(lines)
    else:
        warnings.append("no OCR engine installed (install tesseract-ocr or the 'ocr-rapid' extra)")
    return ExtractedDocument(
        filename=filename,
        kind="image",
        text=text.strip(),
        extractor=f"ocr:{backend}",
        warnings=warnings,
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------- excel ----


def extract_xlsx(data: bytes, filename: str) -> ExtractedDocument:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    tables: list[ExtractedTable] = []
    lines: list[str] = []
    for ws in wb.worksheets[:5]:
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else _cell(v) for v in row]
            if any(cells):
                rows.append(cells)
                lines.append(_row_text(cells))
        if rows:
            tables.append(ExtractedTable(source=f"{filename}!{ws.title}", rows=rows))
    return ExtractedDocument(
        filename=filename,
        kind="xlsx",
        text="\n".join(lines),
        tables=tables,
        extractor="openpyxl",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _cell(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)


def _row_text(cells: list[str]) -> str:
    """Key/value rows ("Total Due", "$4,780.00") read as `Total Due: $4,780.00` so the deterministic field
    patterns (which expect a label separator) see the same text a PDF or email body would carry."""
    filled = [c for c in cells if c]
    if len(filled) == 2 and not filled[0].endswith(":") and len(filled[0]) <= 40:
        return f"{filled[0]}: {filled[1]}"
    return "\t".join(filled)


# ------------------------------------------------------------------ CSV ----


def extract_csv(data: bytes, filename: str) -> ExtractedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    lines = [_row_text(r) for r in rows]
    return ExtractedDocument(
        filename=filename,
        kind="csv",
        text="\n".join(lines),
        tables=[ExtractedTable(source=filename, rows=rows)] if rows else [],
        extractor="csv",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def extract_text(data: bytes, filename: str, kind: str = "text") -> ExtractedDocument:
    return ExtractedDocument(
        filename=filename,
        kind=kind,  # type: ignore[arg-type]
        text=data.decode("utf-8", errors="replace").strip(),
        extractor="text",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def extract_file(data: bytes, filename: str, content_type: str | None = None) -> ExtractedDocument:
    kind = detect_kind(filename, content_type, data)
    if kind == "pdf":
        return extract_pdf(data, filename)
    if kind == "image":
        return extract_image(data, filename)
    if kind == "xlsx":
        return extract_xlsx(data, filename)
    if kind == "csv":
        return extract_csv(data, filename)
    if kind == "text":
        return extract_text(data, filename)
    doc = extract_text(data, filename, "unknown")
    doc.warnings.append(f"unknown file type for {filename!r}; treated as text")
    return doc


def normalize_text(text: str) -> str:
    """Whitespace-normalize while keeping line structure (labels and values stay together)."""
    lines = [" ".join(ln.split()) for ln in text.replace("\r", "\n").splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def combine_documents(docs: list[ExtractedDocument]) -> str:
    parts = []
    for d in docs:
        header = f"[[ {d.kind}: {d.filename} ]]"
        parts.append(header + "\n" + normalize_text(d.text))
        for t in d.tables:
            parts.append(f"[[ table: {t.source} ]]\n" + "\n".join(" | ".join(r) for r in t.rows))
    return "\n\n".join(parts).strip()
