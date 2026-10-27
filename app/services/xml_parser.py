
from lxml import etree
import re

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_REGEX = re.compile(r"\b(?:19|20)\d{2}\b")


def extract_references(xml_text: str) -> list[dict]:
    """
    Convert GROBID TEI XML output into reference dictionaries.
    Extracts title, DOI, authors, and publication year when available.
    """
    root = etree.fromstring(xml_text.encode("utf-8"))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    references = []

    for bibl in root.findall(".//tei:biblStruct", namespaces=ns):
        # Title
        title_el = bibl.find(".//tei:title", namespaces=ns)
        title = (
            title_el.text.strip()
            if title_el is not None and title_el.text
            else None
        )

        # DOI
        doi = None
        for idno in bibl.findall(".//tei:idno", namespaces=ns):
            type_attr = (idno.get("type") or "").lower()
            if "doi" in type_attr and idno.text:
                doi = idno.text.strip()
                break

        # Fallback: DOI regex from raw XML
        if not doi:
            raw = etree.tostring(bibl, encoding="unicode")
            match = DOI_REGEX.search(raw)
            if match:
                doi = match.group(0)

        # Authors
        authors = []
        for author in bibl.findall(".//tei:author", namespaces=ns):
            surname = author.find(".//tei:surname", namespaces=ns)
            forename = author.find(".//tei:forename", namespaces=ns)

            if surname is not None and surname.text:
                name = ""
                if forename is not None and forename.text:
                    name += forename.text.strip() + " "
                name += surname.text.strip()
                authors.append(name)

        # Publication year
        year = None

        # Prefer publication date from imprint.
        date_elements = bibl.findall(
            ".//tei:imprint/tei:date",
            namespaces=ns,
        )

        # Fallback to any date in this reference.
        if not date_elements:
            date_elements = bibl.findall(".//tei:date", namespaces=ns)

        for date_el in date_elements:
            date_value = date_el.get("when") or " ".join(date_el.itertext())
            match = YEAR_REGEX.search(date_value)
            if match:
                year = int(match.group(0))
                break

        references.append({
            "title": title,
            "doi": doi,
            "authors": authors,
            "year": year,
        })

    return references
