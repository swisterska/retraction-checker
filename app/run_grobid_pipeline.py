
import json

from app.services.grobid import parse_references
from app.services.xml_parser import extract_references
from app.services.pubmed import enrich_with_pmid
from app.services.retractions import (
    RetractionService,
    should_update,
    update_retractions_from_gitlab,
)

CSV_PATH = "retractions.csv"


def process_pdf(pdf_path: str) -> list[dict]:
    """Extract references from a PDF and check their retraction status."""

    if should_update(CSV_PATH):
        update_retractions_from_gitlab(CSV_PATH)

    xml = parse_references(pdf_path)
    refs = extract_references(xml)
    print("Number of references:", len(refs))

    enriched = enrich_with_pmid(refs)

    retraction_service = RetractionService(CSV_PATH)
    enriched = retraction_service.mark_retracted(enriched)

    retracted_count = sum(1 for ref in enriched if ref.get("retracted"))
    print("Retracted articles:", retracted_count)

    return enriched


def main():
    enriched = process_pdf("uploads/test.pdf")

    with open("references_enriched_new.json", "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print("Saved references_enriched_new.json")


if __name__ == "__main__":
    main()
