
import logging
import re

from lxml import etree

from app.services.doi import normalize_doi


logger = logging.getLogger(__name__)

DOI_REGEX = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    re.IGNORECASE,
)

YEAR_REGEX = re.compile(r"\b(?:19|20)\d{2}\b")

TEI_NAMESPACE = {
    "tei": "http://www.tei-c.org/ns/1.0"
}


def extract_references(xml_text: str) -> list[dict]:
    """
    Convert GROBID TEI XML output into reference dictionaries.

    Extracts title, DOI, authors, and publication year when available.
    """

    if not isinstance(xml_text, str) or not xml_text.strip():
        raise ValueError("TEI XML content cannot be empty.")

    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except etree.XMLSyntaxError:
        logger.exception("Could not parse GROBID TEI XML.")
        raise

    references = []

    bibliography = root.findall(
        ".//tei:biblStruct",
        namespaces=TEI_NAMESPACE,
    )

    logger.info(
        "Extracting bibliographic references from TEI XML: %d entries found.",
        len(bibliography),
    )

    for bibl in bibliography:

        # Title
        title_el = bibl.find(
            ".//tei:title",
            namespaces=TEI_NAMESPACE,
        )

        title = (
            " ".join(" ".join(title_el.itertext()).split())
            if title_el is not None
            else None
        )

        # DOI
        doi = None

        for idno in bibl.findall(
            ".//tei:idno",
            namespaces=TEI_NAMESPACE,
        ):
            type_attr = (idno.get("type") or "").lower()

            if "doi" in type_attr and idno.text:
                doi = normalize_doi(idno.text)
                break

        # Fallback: DOI regex from raw XML
        if not doi:
            raw = etree.tostring(
                bibl,
                encoding="unicode",
            )

            match = DOI_REGEX.search(raw)

            if match:
                doi = normalize_doi(match.group(0))

        # Authors
        authors = []

        for author in bibl.findall(
            ".//tei:author",
            namespaces=TEI_NAMESPACE,
        ):
            surname = author.find(
                ".//tei:surname",
                namespaces=TEI_NAMESPACE,
            )

            forename = author.find(
                ".//tei:forename",
                namespaces=TEI_NAMESPACE,
            )

            if surname is not None and surname.text:
                name_parts = []

                if forename is not None and forename.text:
                    name_parts.append(forename.text.strip())

                name_parts.append(surname.text.strip())

                authors.append(" ".join(name_parts))

        # Publication year
        year = None

        date_elements = bibl.findall(
            ".//tei:imprint/tei:date",
            namespaces=TEI_NAMESPACE,
        )

        if not date_elements:
            date_elements = bibl.findall(
                ".//tei:date",
                namespaces=TEI_NAMESPACE,
            )

        for date_el in date_elements:
            date_value = (
                date_el.get("when")
                or " ".join(date_el.itertext())
            )

            match = YEAR_REGEX.search(date_value)

            if match:
                year = int(match.group(0))
                break

        # Full-document GROBID output can contain a placeholder biblStruct
        # outside the actual bibliography. Keep only entries with metadata.
        if not (title or doi or authors or year):
            continue

        references.append({
            "title": title,
            "doi": doi,
            "authors": authors,
            "year": year,
        })

    logger.info(
        "TEI extraction completed: %d references extracted.",
        len(references),
    )

    return references
