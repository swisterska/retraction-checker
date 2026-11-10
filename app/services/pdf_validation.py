import logging
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


logger = logging.getLogger(__name__)


class PdfValidationError(ValueError):
    """A user-correctable PDF input error with a safe API response."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_pdf(stream: BinaryIO) -> None:
    """Check PDF readability and embedded text before external analysis."""

    try:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise PdfValidationError(
                "PDF_ENCRYPTED",
                "This PDF is password-protected and cannot be read.",
            )

        has_readable_text = any(
            (page.extract_text() or "").strip()
            for page in reader.pages
        )
    except PdfValidationError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError) as exc:
        logger.warning("Uploaded PDF could not be read by the PDF parser.", exc_info=True)
        raise PdfValidationError(
            "PDF_CORRUPTED",
            "The PDF file appears to be corrupted or unreadable.",
        ) from exc
    except Exception as exc:
        # PDF parsers can raise format-specific exceptions while decoding
        # page content. Keep those details in logs, not in the API response.
        logger.exception("Unexpected error while validating uploaded PDF.")
        raise PdfValidationError(
            "PDF_CORRUPTED",
            "The PDF file appears to be corrupted or unreadable.",
        ) from exc

    if not has_readable_text:
        raise PdfValidationError(
            "NO_READABLE_TEXT",
            "No readable text was found in this document.",
        )
