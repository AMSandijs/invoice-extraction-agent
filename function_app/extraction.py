"""GPT-4o invoice extraction for the Azure Function.

Ported from extractor.py. Uses PyMuPDF to render scanned PDFs to images so the
Function needs no system binaries (pdf2image's poppler dependency is dropped).
"""

import io
import base64
import json

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


# Extraction prompt — carried over verbatim from extractor.py (Phase 1).
SYSTEM_PROMPT = """You are a precise invoice data extraction assistant.
Extract the following fields from the invoice and return ONLY a valid JSON object — no markdown, no explanation.

Required fields:
  invoice_number   - The invoice identifier/reference number (string)
  invoice_date     - Date the invoice was issued (ISO 8601 if possible, e.g. "2024-03-15")
  supplier_name    - Name of the company or person issuing the invoice (string)
  total_amount     - Final total payable amount as a number (float, no currency symbol)
  currency         - 3-letter ISO currency code if determinable (e.g. "EUR", "USD"), else the symbol

Optional fields (include if present, otherwise use null):
  buyer_name       - Name of the customer / billed party
  due_date         - Payment due date (ISO 8601)
  subtotal         - Amount before tax (float)
  tax_amount       - Total tax amount (float)
  tax_rate         - Tax percentage as a string (e.g. "21%")
  po_number        - Purchase order number
  payment_terms    - Payment terms (e.g. "Net 30")
  line_items       - Array of line items, each: {"description": str, "quantity": num, "unit_price": num, "total": num}

Rules:
  - Return ONLY the JSON object. No prose.
  - Use null for any field that cannot be found or inferred.
  - Numbers must be plain floats (e.g. 1234.56), never strings with symbols.
"""


def _chat_extract_text(client, deployment: str, text: str) -> dict:
    """Send invoice text to GPT-4o and parse the structured JSON reply."""
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract invoice data from the following text.\n\n"
                    f"--- INVOICE TEXT START ---\n{text}\n--- INVOICE TEXT END ---"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def _chat_extract_images(client, deployment: str, png_pages: list[bytes]) -> dict:
    """Send page images to GPT-4o Vision and parse the structured JSON reply."""
    content = [{"type": "text", "text": "Extract all invoice data from the image(s) below."}]
    for png in png_pages:
        b64 = base64.b64encode(png).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            }
        )
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def extract(client, deployment: str, blob_name: str, data: bytes) -> tuple[dict, str]:
    """Extract invoice fields from a file.

    Returns (fields_dict, method). Raises ValueError for unsupported files;
    other failures (bad JSON, API errors) propagate to the caller.
    """
    strategy = detect_strategy(blob_name, data)
    if strategy == "unsupported":
        raise ValueError(f"Unsupported file type: {blob_name}")
    if strategy == "text":
        return _chat_extract_text(client, deployment, _pdf_text(data)), "text+gpt4o"
    if strategy == "vision-pdf":
        return _chat_extract_images(client, deployment, _pdf_to_png_pages(data)), "vision+gpt4o"
    return _chat_extract_images(client, deployment, [_image_to_png(data)]), "vision+gpt4o"
