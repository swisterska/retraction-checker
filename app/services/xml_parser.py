from lxml import etree
import re

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)

def extract_references(xml_text: str) -> list[dict]:
    """
    Convert GROBID TEI XML output into a list of reference dictionaries.

    Args:
        xml_text (str): XML string returned by GROBID containing
        bibliographic references in TEI format.

    Returns:
        list[dict]: List of references where each reference is represented
        as a dictionary with keys "title", "doi", and "authors".
    """

    root = etree.fromstring(xml_text.encode("utf-8"))
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    references = []

    for bibl in root.findall(".//tei:biblStruct", namespaces=ns):

        # title
        title_el = bibl.find(".//tei:title", namespaces=ns)
        title = title_el.text.strip() if title_el is not None and title_el.text else None

        # DOI (case-insensitive)
        doi = None
        for idno in bibl.findall(".//tei:idno", namespaces=ns):
            type_attr = (idno.get("type") or "").lower()
            if "doi" in type_attr and idno.text:
                doi = idno.text.strip()
                break

        # fallback: DOI regex from raw XML text
        if not doi:
            raw = etree.tostring(bibl, encoding="unicode")
            match = DOI_REGEX.search(raw)
            if match:
                doi = match.group(0)

        # authors
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

        references.append({
            "title": title,
            "doi": doi,
            "authors": authors
        })

    return references