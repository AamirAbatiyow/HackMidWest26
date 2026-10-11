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


def extract_pdf_ocr(data: bytes, filename: str, max_pages: int = 5) -> ExtractedDocument:
    """Scanned PDF: rasterise the first pages with pdfplumber (pypdfium2) and OCR them.

    Used when the text layer is empty and an OCR engine exists; otherwise ``extract_pdf``'s result with
    its "no text layer" warning stands and the submission is kicked back to the sender.
    """
    doc = extract_pdf(data, filename)
    backend = ocr_backend()
    if doc.text or backend == "none":
        if not doc.text:
            doc.warnings.append(NO_OCR_WARNING.replace("image left unread", "scanned PDF left unread"))
        return doc
    texts: list[str] = []
    warnings = [w for w in doc.warnings if not w.startswith("no text layer")]
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:max_pages]:
                png = io.BytesIO()
                page.to_image(resolution=200).original.save(png, format="PNG")
                texts.append(extract_image(png.getvalue(), filename).text)
            if len(pdf.pages) > max_pages:
                warnings.append(f"only the first {max_pages} pages were OCRed")
    except Exception as exc:  # pragma: no cover - depends on the local raster/OCR stack
        warnings.append(f"PDF OCR failed: {exc}")
    text = "\n".join(t for t in texts if t).strip()
    if not text:
        warnings.append("OCR found no text in the scanned PDF")
    return ExtractedDocument(
        filename=filename,
        kind="pdf",
        text=text,
        tables=doc.tables,
        extractor="pypdf+pdfplumber+ocr",
        warnings=warnings,
        sha256=doc.sha256,
    )


# ---------------------------------------------------------------- image ----


OCR_INSTALL_HINT = "apt-get install tesseract-ocr tesseract-ocr-eng (or the 'ocr-rapid' extra)"
NO_OCR_WARNING = f"no OCR engine installed on this server ({OCR_INSTALL_HINT}); image left unread"


_ocr_cache: dict[str, object] = {}  # "backend" once an engine is found; "warned" after the first miss


def _probe_ocr_backend() -> str:
    try:
        import pytesseract  # noqa: F401

        if shutil.which("tesseract"):
            return "tesseract"
    except Exception as exc:  # pragma: no cover
        log.debug("pytesseract unavailable: %s", exc)
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return "rapidocr"
    except Exception:
        return "none"


def ocr_backend() -> str:
    """Which OCR engine is available: 'tesseract', 'rapidocr' or 'none'.

    A found engine is remembered for the life of the process. A *missing* engine is re-probed on every call
    (a PATH lookup) so that `apt-get install tesseract-ocr` inside the running container takes effect on the
    next intake without a restart; the miss is logged once at WARNING so it shows up in the boot logs
    (``/v1/health`` and ``/health`` report the same thing to the operator).
    """
    found = _ocr_cache.get("backend")
    if found:
        return str(found)
    backend = _probe_ocr_backend()
    if backend != "none":
        _ocr_cache["backend"] = backend
        _live_ocr_status.cache_clear()
    elif not _ocr_cache.get("warned"):
        _ocr_cache["warned"] = True
        log.warning(
            "no OCR engine: image invoices (PNG/JPEG) and scanned PDFs cannot be read; %s",
            OCR_INSTALL_HINT,
            extra={"ocr_backend": "none"},
        )
    return backend


def ocr_status() -> dict:
    """Operator-facing OCR facts for the health endpoints.

    ``state`` is ``live`` when an engine can read images and ``down`` otherwise; ``tesseract_version`` and
    ``languages`` come from the binary when it is the engine (``eng`` must be present for invoices).
    Only a live answer is cached (it shells out to tesseract); "down" is re-evaluated on each poll.
    """
    if ocr_backend() == "none":
        return {
            "state": "down",
            "backend": "none",
            "tesseract_version": None,
            "languages": [],
            "detail": f"no OCR engine: image invoices are held as unreadable; {OCR_INSTALL_HINT}",
        }
    status = _live_ocr_status()
    if status["state"] != "live":  # e.g. English data missing: re-check once it is installed
        _live_ocr_status.cache_clear()
    return dict(status)


@lru_cache(maxsize=1)
def _live_ocr_status() -> dict:
    backend = ocr_backend()
    status: dict = {
        "state": "live" if backend != "none" else "down",
        "backend": backend,
        "tesseract_version": None,
        "languages": [],
        "detail": "",
    }
    if backend == "tesseract":
        import pytesseract

        try:
            status["tesseract_version"] = str(pytesseract.get_tesseract_version())
        except Exception as exc:  # pragma: no cover - broken install
            status["state"], status["detail"] = "down", f"tesseract present but not runnable: {exc}"
            return status
        try:
            status["languages"] = sorted(lang for lang in pytesseract.get_languages() if lang != "osd")
        except Exception as exc:  # pragma: no cover - old tesseract without --list-langs
            log.debug("tesseract languages unavailable: %s", exc)
        if status["languages"] and "eng" not in status["languages"]:
            status["state"] = "down"
            status["detail"] = (
                f"tesseract {status['tesseract_version']} has no English data: apt-get install tesseract-ocr-eng"
            )
        else:
            status["detail"] = (
                f"tesseract {status['tesseract_version']} · languages {', '.join(status['languages']) or '?'}"
            )
    else:
        status["detail"] = "rapidocr-onnxruntime (pure-Python fallback; no tesseract binary)"
    return status


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
        warnings.append(NO_OCR_WARNING)
        log.warning("image %s left unread: no OCR engine", filename, extra={"ocr_backend": backend})
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
