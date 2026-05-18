import pytest
from unittest.mock import MagicMock

import extraction


def test_detect_strategy_image_extensions():
    assert extraction.detect_strategy("scan.png", b"") == "vision-image"
    assert extraction.detect_strategy("photo.JPG", b"") == "vision-image"


def test_detect_strategy_unsupported():
    assert extraction.detect_strategy("notes.txt", b"") == "unsupported"
    assert extraction.detect_strategy("noextension", b"") == "unsupported"


def test_detect_strategy_text_pdf(text_pdf_bytes):
    assert extraction.detect_strategy("invoice.pdf", text_pdf_bytes) == "text"


def test_detect_strategy_scanned_pdf(blank_pdf_bytes):
    assert extraction.detect_strategy("scan.pdf", blank_pdf_bytes) == "vision-pdf"


_VALID_JSON = '{"invoice_number": "INV-001", "supplier_name": "Acme Corp", "total_amount": 1250.0, "currency": "EUR"}'


def test_extract_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extraction.extract(MagicMock(), "gpt-4o", "notes.txt", b"")


def test_extract_image_path(make_chat_client, png_bytes):
    client = make_chat_client(_VALID_JSON)
    data, method = extraction.extract(client, "gpt-4o", "receipt.png", png_bytes)
    assert data["invoice_number"] == "INV-001"
    assert method == "vision+gpt4o"
    client.chat.completions.create.assert_called_once()


def test_extract_text_pdf_path(make_chat_client, text_pdf_bytes):
    client = make_chat_client(_VALID_JSON)
    data, method = extraction.extract(client, "gpt-4o", "invoice.pdf", text_pdf_bytes)
    assert data["supplier_name"] == "Acme Corp"
    assert method == "text+gpt4o"


def test_extract_vision_pdf_path(make_chat_client, blank_pdf_bytes):
    client = make_chat_client(_VALID_JSON)
    data, method = extraction.extract(client, "gpt-4o", "scan.pdf", blank_pdf_bytes)
    assert data["invoice_number"] == "INV-001"
    assert method == "vision+gpt4o"
    client.chat.completions.create.assert_called_once()
