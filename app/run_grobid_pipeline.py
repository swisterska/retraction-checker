import json
import os

from services.grobid import parse_references
from services.xml_parser import extract_references
from services.pubmed import enrich_with_pmid
from services.retractions import (
    RetractionService,
    should_update,
    update_retractions_from_pubmed
)

# CONFIG
CSV_PATH = "retractions.csv"


def main():
    # Auto uopdate (PubMed)
    if should_update(CSV_PATH):
        update_retractions_from_pubmed(CSV_PATH)

    # Grobid
    xml = parse_references("uploads/test.pdf")
    refs = extract_references(xml)

    print("Number of references:", len(refs))

    # PubMed enrichment 
    enriched = enrich_with_pmid(refs)

    #  Retraction detection
    retraction_service = RetractionService(CSV_PATH)
    enriched = retraction_service.mark_retracted(enriched)

    retracted_count = sum(1 for r in enriched if r.get("retracted"))
    print("Retracted articles:", retracted_count)

    #  Sample output 
    print(enriched[:3])

    #  Save results 
    output_path = "references_enriched_new.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print(f"Saved {output_path}")

    #  Stats 
    
    missing = [r for r in enriched if not r.get("doi")]

    print("Missing DOI:", len(missing))

    for r in missing[:10]:
        print(r.get("title"))


if __name__ == "__main__":
    main()