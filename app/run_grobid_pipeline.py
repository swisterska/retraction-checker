
import logging
import os
import time

from app.services.grobid import parse_references
from app.services.xml_parser import extract_references
from app.services.pubmed import enrich_with_pmid
from app.services.retractions import (
    RetractionService,
    ensure_retractions_dataset,
)

import argparse



logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

CSV_PATH = os.path.join(PROJECT_ROOT, "retractions.csv")


def process_pdf(pdf_path: str) -> list[dict]:
    """
    Extract references from a PDF, enrich them with PubMed IDs
    and check their retraction status.
    """

    start_time = time.perf_counter()

    logger.info(
        "Starting complete PDF analysis: %s",
        os.path.basename(pdf_path),
    )

    try:
        # Step 1: Ensure Retraction Watch dataset is available.
        ensure_retractions_dataset(CSV_PATH)

        # Step 2: Load the local Retraction Watch dataset.
        retraction_service = RetractionService(CSV_PATH)

        # Step 3: Extract references using GROBID.
        xml = parse_references(pdf_path)
        refs = extract_references(xml)

        logger.info(
            "Reference extraction completed: %d references found.",
            len(refs),
        )

        # Step 4: Enrich references with PubMed IDs.
        enriched = enrich_with_pmid(refs)

        # Step 5: Detect retracted publications.
        enriched = retraction_service.mark_retracted(enriched)

        retracted_count = sum(
            1 for ref in enriched if ref.get("retracted")
        )

        elapsed_time = time.perf_counter() - start_time

        logger.info(
            "PDF analysis completed: "
            "references=%d, retracted=%d, duration=%.2f seconds.",
            len(enriched),
            retracted_count,
            elapsed_time,
        )

        return enriched

    except Exception:
        logger.exception(
            "PDF analysis failed for file: %s",
            os.path.basename(pdf_path),
        )
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Run the Retraction Checker PDF analysis pipeline."
    )

    default_pdf = os.path.join(
        PROJECT_ROOT,
        "app",
        "tests",
        "fixtures",
        "test.pdf",
    )

    parser.add_argument(
        "pdf_path",
        nargs="?",
        default=default_pdf,
        help="Path to the PDF file to analyze.",
    )

    args = parser.parse_args()
    pdf_path = os.path.abspath(args.pdf_path)

    if not os.path.isfile(pdf_path):
        parser.error(f"PDF file does not exist: {pdf_path}")

    enriched = process_pdf(pdf_path)

    OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output_path = os.path.join(
        OUTPUT_DIR,
        "references_enriched_new.json",
    )

    import json

    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(
            enriched,
            output_file,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(
        "Saved enriched references to: %s",
        output_path,
    )


if __name__ == "__main__":
    main()
