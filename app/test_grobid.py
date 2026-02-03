import json

from services.grobid import parse_references
from services.xml_parser import extract_references
from services.pubmed import enrich_with_pmid

xml = parse_references("../uploads/test.pdf")

refs = extract_references(xml)

print("Number of references:", len(refs))
enriched = enrich_with_pmid(refs)

print(enriched[:3])

with open("../references_enriched.json", "w", encoding="utf-8") as f:
    json.dump(enriched, f, indent=2, ensure_ascii=False)

print("Saved references_enriched.json")
