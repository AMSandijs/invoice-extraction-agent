"""Pytest configuration and shared fixtures for the Function app tests."""

import io
from unittest.mock import MagicMock

import fitz  # PyMuPDF
import pytest
from PIL import Image


@pytest.fixture
def png_bytes():
    """A minimal valid PNG image as bytes."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def text_pdf_bytes():
    """A PDF carrying enough machine-readable text to count as text-based."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Invoice number INV-001 supplier Acme Corp. " * 8)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def blank_pdf_bytes():
    """A PDF with a page but no extractable text — stands in for a scan."""
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def make_chat_client():
    """Factory: a fake OpenAI client whose chat completion returns json_content."""
    def _make(json_content):
        client = MagicMock()
        choice = MagicMock()
        choice.message = MagicMock(content=json_content)
        client.chat.completions.create.return_value.choices = [choice]
        return client
    return _make
