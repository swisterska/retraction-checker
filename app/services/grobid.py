
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
GROBID_FULLTEXT_URL = os.getenv(
    "GROBID_FULLTEXT_URL",
    f"{GROBID_URL.rsplit('/', 1)[0]}/processFulltextDocument",
)
GROBID_TIMEOUT = float(os.getenv("GROBID_TIMEOUT", "300"))
GROBID_RETRY_ATTEMPTS = int(os.getenv("GROBID_RETRY_ATTEMPTS", "3"))
GROBID_RETRY_BACKOFF_SECONDS = float(
    os.getenv("GROBID_RETRY_BACKOFF_SECONDS", "1.0")
)


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

    last_error = None

    for attempt in range(1, GROBID_RETRY_ATTEMPTS + 1):
        try:
            with open(pdf_path, "rb") as pdf_file:
                response = requests.post(
                    GROBID_URL,
                    files={"input": pdf_file},
                    timeout=GROBID_TIMEOUT,
                )

            response.raise_for_status()

        except requests.exceptions.Timeout as exc:
            last_error = exc
            logger.warning(
                "GROBID request timed out for file: %s (attempt %s/%s)",
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    f"GROBID request timed out after {GROBID_TIMEOUT} seconds."
                ) from exc
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        except requests.exceptions.ConnectionError as exc:
            last_error = exc
            logger.warning(
                "Cannot connect to GROBID at %s while processing file: %s (attempt %s/%s)",
                GROBID_URL,
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    f"Cannot connect to GROBID at {GROBID_URL}. "
                    "Check whether the GROBID service is running."
                ) from exc
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        except requests.exceptions.HTTPError as exc:
            last_error = exc
            status_code = (
                exc.response.status_code
                if exc.response is not None
                else "unknown"
            )
            logger.warning(
                "GROBID returned HTTP error %s for file: %s (attempt %s/%s)",
                status_code,
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    f"GROBID returned HTTP error {status_code}."
                ) from exc
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        except requests.exceptions.RequestException as exc:
            last_error = exc
            logger.warning(
                "GROBID request failed for file: %s (attempt %s/%s): %s",
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
                exc,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    f"GROBID request failed: {exc}"
                ) from exc
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        xml_content = response.text.strip()

        if not xml_content:
            logger.warning(
                "GROBID returned an empty response for file: %s (attempt %s/%s)",
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                logger.warning(
                    "GROBID returned no references for %s; trying full-text extraction.",
                    filename,
                )
                try:
                    with open(pdf_path, "rb") as pdf_file:
                        fallback_response = requests.post(
                            GROBID_FULLTEXT_URL,
                            files={"input": pdf_file},
                            timeout=GROBID_TIMEOUT,
                        )
                    fallback_response.raise_for_status()
                except requests.exceptions.RequestException as exc:
                    raise GrobidServiceError(
                        "GROBID returned an empty response and full-text extraction failed."
                    ) from exc

                fallback_xml = fallback_response.text.strip()
                if not fallback_xml:
                    raise GrobidServiceError(
                        "GROBID returned an empty response for both reference and full-text extraction."
                    )
                try:
                    fallback_root = etree.fromstring(fallback_xml.encode("utf-8"))
                except etree.XMLSyntaxError as exc:
                    raise GrobidServiceError(
                        "GROBID full-text extraction returned invalid XML."
                    ) from exc
                if etree.QName(fallback_root).localname != "TEI":
                    raise GrobidServiceError(
                        "GROBID full-text extraction returned an unexpected response."
                    )
                logger.info(
                    "GROBID full-text fallback completed for file: %s",
                    filename,
                )
                return fallback_xml
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        try:
            root = etree.fromstring(xml_content.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            logger.warning(
                "GROBID returned invalid XML for file: %s (attempt %s/%s)",
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    "GROBID returned invalid XML."
                ) from exc
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        root_name = etree.QName(root).localname

        if root_name != "TEI":
            logger.warning(
                "GROBID returned unexpected XML root '%s' for file: %s (attempt %s/%s)",
                root_name,
                filename,
                attempt,
                GROBID_RETRY_ATTEMPTS,
            )
            if attempt == GROBID_RETRY_ATTEMPTS:
                raise GrobidServiceError(
                    f"GROBID returned an unexpected XML root element: "
                    f"{root_name!r}. Expected 'TEI'."
                )
            time.sleep(GROBID_RETRY_BACKOFF_SECONDS * attempt)
            continue

        elapsed_time = time.perf_counter() - start_time

        logger.info(
            "GROBID processing completed for file: %s (%.2f seconds)",
            filename,
            elapsed_time,
        )

        return xml_content

    raise GrobidServiceError(
        f"GROBID processing failed for {filename}: {last_error}"
    )
