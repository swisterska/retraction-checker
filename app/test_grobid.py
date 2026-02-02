import json

from services.grobid import parse_references
from services.xml_parser import extract_references

xml = parse_references("../uploads/test.pdf")

refs = extract_references(xml)

print("Number of references:", len(refs))

with open("../references.json", "w", encoding="utf-8") as f:
    json.dump(refs, f, indent=2, ensure_ascii=False)

print("Saved to references.json")
