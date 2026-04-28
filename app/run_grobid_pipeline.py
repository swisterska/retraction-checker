import json

from services.grobid import parse_references
from services.xml_parser import extract_references
from services.pubmed import enrich_with_pmid
from services.retractions import (
    RetractionService,
    should_update,
    update_retractions_from_gitlab
)

# CONFIG
CSV_PATH = "retractions.csv"


def main():

    # UPDATE DATASET 
    if should_update(CSV_PATH):
        update_retractions_from_gitlab(CSV_PATH)

    # GROBID 
    xml = parse_references("uploads/test.pdf")
    refs = extract_references(xml)
    

    print("Number of references:", len(refs))

    # PubMed
    enriched = enrich_with_pmid(refs)

    # RETRACTIONS
    retraction_service = RetractionService(CSV_PATH)
    enriched = retraction_service.mark_retracted(enriched)

    retracted_count = sum(1 for r in enriched if r.get("retracted"))
    print("Retracted articles:", retracted_count)

    print(enriched[:3])

    with open("references_enriched_new.json", "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print("Saved references_enriched_new.json")


if __name__ == "__main__":
    main()