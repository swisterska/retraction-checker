
import logging
import os
import time

import requests
from lxml import etree


logger = logging.getLogger(__name__)

GROBID_URL = os.getenv(
    "GROBID_URL",
    "http://localhost:8070/api/processReferences",
)
GROBID_TIMEOUT = float(os.getenv("GROBID_TIMEOUT", "120"))


class GrobidServiceError(RuntimeError):
    """Raised when GROBID cannot return valid TEI XML."""


def parse_references(pdf_path: str) -> str:
    """
    Extract bibliographic references from a PDF using GROBID.

    Returns:
        TEI XML returned by GROBID.

    Raises:
        FileNotFoundError: The PDF file does not exist.
        GrobidServiceError: GROBID is unavailable or returns invalid data.
    """

    start_time = time.perf_counter()
    filename = os.path.basename(pdf_path)

    logger.info("Starting GROBID processing for file: %s", filename)

    try:
        with open(pdf_path, "rb") as pdf_file:
            response = requests.post(
                GROBID_URL,
                files={"input": pdf_file},
                timeout=GROBID_TIMEOUT,
            )

        response.raise_for_status()

    except requests.exceptions.Timeout as exc:
        logger.error(
            "GROBID request timed out after %s seconds for file: %s",
            GROBID_TIMEOUT,
            filename,
        )
        raise GrobidServiceError(
            f"GROBID request timed out after {GROBID_TIMEOUT} seconds."
        ) from exc

    except requests.exceptions.ConnectionError as exc:
        logger.error(
            "Cannot connect to GROBID at %s while processing file: %s",
            GROBID_URL,
            filename,
        )
        raise GrobidServiceError(
            f"Cannot connect to GROBID at {GROBID_URL}. "
            "Check whether the GROBID service is running."
        ) from exc

    except requests.exceptions.HTTPError as exc:
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else "unknown"
        )
        logger.error(
            "GROBID returned HTTP error %s for file: %s",
            status_code,
            filename,
        )
        raise GrobidServiceError(
            f"GROBID returned HTTP error {status_code}."
        ) from exc

    except requests.exceptions.RequestException as exc:
        logger.exception(
            "GROBID request failed for file: %s",
            filename,
        )
        raise GrobidServiceError(
            f"GROBID request failed: {exc}"
        ) from exc

    xml_content = response.text.strip()

    if not xml_content:
        logger.warning(
            "GROBID returned an empty response for file: %s",
            filename,
        )
        raise GrobidServiceError(
            "GROBID returned an empty response."
        )

    try:
        root = etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        logger.warning(
            "GROBID returned invalid XML for file: %s",
            filename,
        )
        raise GrobidServiceError(
            "GROBID returned invalid XML."
        ) from exc

    root_name = etree.QName(root).localname

    if root_name != "TEI":
        logger.warning(
            "GROBID returned unexpected XML root '%s' for file: %s",
            root_name,
            filename,
        )
        raise GrobidServiceError(
            f"GROBID returned an unexpected XML root element: "
            f"{root_name!r}. Expected 'TEI'."
        )

    elapsed_time = time.perf_counter() - start_time

    logger.info(
        "GROBID processing completed for file: %s (%.2f seconds)",
        filename,
        elapsed_time,
    )

    return xml_content
