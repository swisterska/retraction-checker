import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.services.pdf_validation import PdfValidationError, validate_pdf


VALID_PDF_PATH = Path(__file__).parent / "fixtures" / "testychat.pdf"


def test_validate_pdf_accepts_readable_pdf():
    validate_pdf(io.BytesIO(VALID_PDF_PATH.read_bytes()))


def test_validate_pdf_rejects_corrupted_pdf():
    with pytest.raises(PdfValidationError) as error:
        validate_pdf(io.BytesIO(b"%PDF-1.7\nnot a PDF structure"))

    assert error.value.code == "PDF_CORRUPTED"
    assert error.value.status_code == 422


def test_validate_pdf_rejects_pdf_without_embedded_text():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    stream = io.BytesIO()
    writer.write(stream)
    stream.seek(0)

    with pytest.raises(PdfValidationError) as error:
        validate_pdf(stream)

    assert error.value.code == "NO_READABLE_TEXT"


def test_validate_pdf_rejects_encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("test-password")
    stream = io.BytesIO()
    writer.write(stream)
    stream.seek(0)

    with pytest.raises(PdfValidationError) as error:
        validate_pdf(stream)

    assert error.value.code == "PDF_ENCRYPTED"
