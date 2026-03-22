"""
This script runs the full workflow for extracting bibliographic references
from a PDF file and enriching them with PubMed identifiers (PMIDs).

Pipeline steps:
1. Send the PDF to the GROBID service to extract references as TEI XML.
2. Parse the XML and convert references into Python dictionaries.
3. Query the PubMed API to retrieve PMIDs.
4. Save the enriched references to a JSON file.

The script prints basic progress information and saves the final results
to "references_enriched_new.json".
"""

import json

from services.grobid import parse_references
from services.xml_parser import extract_references
from services.pubmed import enrich_with_pmid
from services.retractions import RetractionService

xml = parse_references("uploads/test.pdf")

refs = extract_references(xml)

print("Number of references:", len(refs))
enriched = enrich_with_pmid(refs)
retraction_service = RetractionService("retractions.csv")

enriched = retraction_service.mark_retracted(enriched)

retracted_count = sum(1 for r in enriched if r.get("retracted"))

print("Retracted articles:", retracted_count)

print(enriched[:3])

with open("references_enriched_new.json", "w", encoding="utf-8") as f:
    json.dump(enriched, f, indent=2, ensure_ascii=False)

print("Saved references_enriched.json")

missing = [r for r in refs if not r["doi"]]

print("Missing DOI:", len(missing))

for r in missing[:10]:
    print(r["title"])
