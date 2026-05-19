# ADR-0001: GPT-4o as the sole extraction engine

**Date:** 2026-05-19  
**Status:** Accepted

## Context

Invoice documents arrive in three forms: text-based PDFs, scanned PDFs (image-only), and raw image files (PNG, JPG). Extracting structured fields from these traditionally requires separate tools per path: a PDF text parser, an OCR engine, and an NLP layer to find and normalize fields.

Alternatives considered:

| Approach | Pros | Cons |
|---|---|---|
| Rule-based regex / scripting | No API cost, fully offline | Brittle against layout variation; separate logic per vendor format |
| Dedicated OCR (Tesseract) + NLP | Offline, open-source | Two-model stack to maintain; poor on handwriting and rotated pages |
| Azure AI Document Intelligence | Purpose-built for documents | Adds a second Azure service; pre-trained model may miss custom fields |
| GPT-4o (text + Vision) | One model, one API, handles all three paths | Per-token cost; requires API key |

## Decision

Use GPT-4o for all three extraction paths:

- **Text PDF** — extract text with `pdfplumber`, pass as a text prompt.
- **Scanned PDF** — rasterise pages with `pdf2image`, pass images to GPT-4o Vision.
- **Image file** — pass directly to GPT-4o Vision.

The model is prompted with `response_format: json_object` and `temperature=0` so output is always valid JSON and deterministic.

## Consequences

- **One code path, one model** — no separate OCR stack; simpler to maintain.
- **Handles all complexity levels** — the same prompt works for clean PDFs and photographed receipts.
- **Per-call cost** — each invoice is one API call. Acceptable for the assignment scale; a batch-processing queue would be needed at production volume.
- **`MAX_VISION_PAGES = 4`** — caps cost on long documents; pages beyond 4 are dropped. Noted limitation.
- **API key required** — not fully offline. Mitigated in Phase 2 by using managed identity against Azure OpenAI.
