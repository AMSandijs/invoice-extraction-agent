"""GPT-4o invoice extraction for the Azure Function.

Ported from extractor.py. Uses PyMuPDF to render scanned PDFs to images so the
Function needs no system binaries (pdf2image's poppler dependency is dropped).
"""

import io
import base64

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image

# A PDF with at least this many extractable characters is treated as text-based.
TEXT_PDF_MIN_CHARS = 200

# Cap the number of PDF pages sent to the vision model (cost control).
MAX_VISION_PAGES = 4

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def _suffix(blob_name: str) -> str:
    """Return the lowercased file extension including the dot, or ''."""
    return "." + blob_name.rsplit(".", 1)[-1].lower() if "." in blob_name else ""


def _pdf_text(data: bytes) -> str:
    """Extract all machine-readable text from a PDF."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        parts = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(parts).strip()


def _pdf_has_text(data: bytes) -> bool:
    """True if the PDF has enough extractable text to skip OCR."""
    try:
        return len(_pdf_text(data)) >= TEXT_PDF_MIN_CHARS
    except Exception:
        return False


def _pdf_to_png_pages(data: bytes) -> list[bytes]:
    """Render the first MAX_VISION_PAGES PDF pages to PNG bytes via PyMuPDF."""
    pages: list[bytes] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page in list(doc)[:MAX_VISION_PAGES]:
            pages.append(page.get_pixmap(dpi=200).tobytes("png"))
    finally:
        doc.close()
    return pages


def _image_to_png(data: bytes) -> bytes:
    """Normalise any image to RGB PNG bytes."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def detect_strategy(blob_name: str, data: bytes) -> str:
    """Return the extraction strategy for a file.

    One of: 'text', 'vision-pdf', 'vision-image', 'unsupported'.
    """
    suffix = _suffix(blob_name)
    if suffix == ".pdf":
        return "text" if _pdf_has_text(data) else "vision-pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "vision-image"
    return "unsupported"
