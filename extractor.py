"""
Invoice Data Extractor — Levels 2 & 3
======================================
Unified pipeline that auto-detects invoice type and uses the optimal strategy:
  - Text-based PDFs  (Level 2) → pdfplumber text extraction + GPT-4o
  - Scanned/image PDFs (Level 3) → GPT-4o Vision (OCR + extraction in one step)
  - Raw image files              → GPT-4o Vision

Usage:
    python extractor.py <folder_path> [--output results.csv]

Requirements:
    pip install -r requirements.txt

--- Provider configuration ---

Option A: Standard OpenAI
    export OPENAI_API_KEY=sk-...

Option B: Azure AI Foundry (Azure OpenAI Service)
    export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
    export AZURE_OPENAI_API_KEY=your-azure-key
    export AZURE_OPENAI_DEPLOYMENT=gpt-4o          # your deployment name
    export AZURE_OPENAI_API_VERSION=2024-12-01-preview  # optional, has a default

The script auto-detects which provider to use based on which env vars are set.
AZURE_OPENAI_ENDPOINT takes priority if present.
"""

import os
import sys
import json
import base64
import argparse
import io
from pathlib import Path

import pdfplumber
import pandas as pd
from openai import OpenAI, AzureOpenAI
from pdf2image import convert_from_path
from PIL import Image


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum number of characters extracted from a PDF before we consider it
# "text-based". Below this threshold we treat it as scanned and use vision.
# Set to 200 to avoid misclassifying handwritten forms that have printed
# field labels (e.g. "DATE:___", "FROM:") but no machine-readable content.
TEXT_PDF_MIN_CHARS = 200

# How many PDF pages to send to the vision model at most (cost control).
MAX_VISION_PAGES = 4

# Default model / deployment name (overridden by AZURE_OPENAI_DEPLOYMENT for Azure)
MODEL = "gpt-4o"

# Fields we always want in the output CSV (even if null)
OUTPUT_COLUMNS = [
    "file",
    "method",
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "buyer_name",
    "total_amount",
    "currency",
    "subtotal",
    "tax_amount",
    "tax_rate",
    "due_date",
    "po_number",
    "payment_terms",
    "line_items",
    "error",
]

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Client factory — supports both OpenAI and Azure AI Foundry
# ---------------------------------------------------------------------------

def get_client() -> tuple[OpenAI | AzureOpenAI, str]:
    """
    Return (client, model_name) based on available environment variables.

    Azure AI Foundry is used when AZURE_OPENAI_ENDPOINT is set.
    Falls back to standard OpenAI otherwise.

    Returns a tuple so callers always use the right model/deployment name.
    """
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    if azure_endpoint:
        # --- Azure AI Foundry path ---
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        if not api_key:
            sys.exit(
                "\n[ERROR] AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_KEY is missing.\n"
                "  Export it before running:\n"
                "    export AZURE_OPENAI_API_KEY=your-azure-key\n"
            )
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", MODEL)
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

        print(f"[Provider] Azure AI Foundry  |  endpoint: {azure_endpoint}  |  deployment: {deployment}")
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment

    else:
        # --- Standard OpenAI path ---
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            sys.exit(
                "\n[ERROR] No API provider configured. Set one of:\n"
                "\n  Standard OpenAI:\n"
                "    export OPENAI_API_KEY=sk-...\n"
                "\n  Azure AI Foundry:\n"
                "    export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/\n"
                "    export AZURE_OPENAI_API_KEY=your-azure-key\n"
                "    export AZURE_OPENAI_DEPLOYMENT=gpt-4o\n"
            )
        print(f"[Provider] OpenAI  |  model: {MODEL}")
        return OpenAI(api_key=api_key), MODEL


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from a PDF using pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts).strip()


def is_text_based(pdf_path: str) -> bool:
    """
    Return True if the PDF contains enough extractable text to be processed
    without OCR (Level 2 path). Falls back to False for scanned documents.
    """
    try:
        text = extract_pdf_text(pdf_path)
        return len(text) >= TEXT_PDF_MIN_CHARS
    except Exception:
        return False


def pdf_to_images(pdf_path: str, dpi: int = 200) -> list[Image.Image]:
    """Convert PDF pages to PIL Images for vision processing."""
    return convert_from_path(pdf_path, dpi=dpi)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def image_to_base64(img: Image.Image) -> str:
    """Encode a PIL Image as a base64 PNG string."""
    buf = io.BytesIO()
    # Convert to RGB to avoid issues with transparency / palette modes
    rgb = img.convert("RGB")
    rgb.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# LLM extraction strategies
# ---------------------------------------------------------------------------

def extract_from_text(client: OpenAI | AzureOpenAI, text: str, model: str) -> dict:
    """
    Level 2 path: send raw text to GPT-4o and ask for structured JSON.
    Fast and cheap — no image encoding needed.
    """
    response = client.chat.completions.create(
        model=model,
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
    raw = response.choices[0].message.content
    return json.loads(raw)


def extract_from_images(client: OpenAI | AzureOpenAI, images: list[Image.Image], model: str) -> dict:
    """
    Level 3 path: send page images directly to GPT-4o Vision.
    Handles scanned PDFs, photos of invoices, and any image-only document.
    """
    pages_to_send = images[:MAX_VISION_PAGES]

    content = [
        {
            "type": "text",
            "text": "Extract all invoice data from the image(s) below.",
        }
    ]

    for img in pages_to_send:
        b64 = image_to_base64(img)
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",   # use high-detail for better accuracy on dense docs
                },
            }
        )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Single-file processor
# ---------------------------------------------------------------------------

def process_file(client: OpenAI | AzureOpenAI, file_path: str, model: str) -> dict:
    """
    Process one invoice file.  Auto-selects the extraction strategy:
      - .pdf  with extractable text → text + GPT-4o   (Level 2)
      - .pdf  without text (scanned) → vision          (Level 3)
      - image files (.png/.jpg/...)  → vision          (Level 3)
    Returns a flat dict ready for CSV output.
    """
    path = Path(file_path)
    result: dict = {col: None for col in OUTPUT_COLUMNS}
    result["file"] = path.name

    try:
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            if is_text_based(file_path):
                # ---- Level 2: text-based PDF ----
                result["method"] = "text+gpt4o"
                text = extract_pdf_text(file_path)
                data = extract_from_text(client, text, model)
            else:
                # ---- Level 3: scanned / image PDF ----
                result["method"] = "vision+gpt4o"
                images = pdf_to_images(file_path)
                data = extract_from_images(client, images, model)

        elif suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}:
            # ---- Level 3: raw image file ----
            result["method"] = "vision+gpt4o"
            img = Image.open(file_path)
            data = extract_from_images(client, [img], model)

        else:
            result["error"] = f"Unsupported file type: {suffix}"
            return result

        # Merge extracted fields into result (preserve column order)
        for key, value in data.items():
            result[key] = value

    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse error: {e}"
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Folder processor
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def process_folder(folder_path: str, output_csv: str = "extracted_invoices.csv") -> pd.DataFrame:
    """
    Iterate over all supported invoice files in a folder, extract data,
    and write results to a CSV file.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        sys.exit(f"[ERROR] Not a directory: {folder_path}")

    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not files:
        print(f"[WARN] No supported invoice files found in: {folder_path}")
        return pd.DataFrame()

    client, model = get_client()
    print(f"\nFound {len(files)} invoice file(s) in '{folder.name}'. Starting extraction...\n")

    results = []
    for i, file in enumerate(files, start=1):
        print(f"  [{i:02d}/{len(files):02d}] {file.name}", end="  →  ", flush=True)
        result = process_file(client, str(file), model)

        method = result.get("method") or "—"
        error = result.get("error")
        if error:
            print(f"✗  ERROR: {error}")
        else:
            print(
                f"✓  ({method})  |  "
                f"#{result.get('invoice_number')}  |  "
                f"{result.get('supplier_name')}  |  "
                f"{result.get('total_amount')} {result.get('currency') or ''}"
            )
        results.append(result)

    # Build dataframe — ensure all expected columns are present
    df = pd.DataFrame(results)
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[OUTPUT_COLUMNS]

    # Serialise line_items lists to JSON strings for CSV compatibility
    if "line_items" in df.columns:
        df["line_items"] = df["line_items"].apply(
            lambda v: json.dumps(v) if isinstance(v, list) else v
        )

    df.to_csv(output_csv, index=False, encoding="utf-8")

    print(f"\n{'─' * 60}")
    print(f"✓  Extraction complete.  Results written to: {output_csv}")
    print(f"   Total files : {len(results)}")
    print(f"   Successful  : {sum(1 for r in results if not r.get('error'))}")
    print(f"   Errors      : {sum(1 for r in results if r.get('error'))}")
    print(f"{'─' * 60}\n")

    return df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract structured data from invoice documents using GPT-4o.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python extractor.py ./invoices
  python extractor.py ./invoices --output my_results.csv

Supported file types: PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP
        """,
    )
    parser.add_argument(
        "folder",
        help="Path to the folder containing invoice files",
    )
    parser.add_argument(
        "--output",
        default="extracted_invoices.csv",
        help="Output CSV filename (default: extracted_invoices.csv)",
    )
    args = parser.parse_args()
    process_folder(args.folder, args.output)


if __name__ == "__main__":
    main()
