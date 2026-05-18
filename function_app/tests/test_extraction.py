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
