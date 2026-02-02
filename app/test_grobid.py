from services.grobid import parse_references

xml = parse_references("../uploads/test.pdf")

print(xml[:1000])
