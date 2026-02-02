from lxml import etree


def extract_references(xml_text: str):
    
    """
    Changing XML from GROBID into reference list (dict).
    """

    root = etree.fromstring(xml_text.encode("utf-8"))

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    references = []

    for bibl in root.findall(".//tei:biblStruct", namespaces=ns):

        # title
        title_el = bibl.find(".//tei:title", namespaces=ns)
        title = title_el.text if title_el is not None else None

        # DOI
        doi_el = bibl.find(".//tei:idno[@type='DOI']", namespaces=ns)
        doi = doi_el.text if doi_el is not None else None

        # authors
        authors = []
        for author in bibl.findall(".//tei:author", namespaces=ns):
            surname = author.find(".//tei:surname", namespaces=ns)
            forename = author.find(".//tei:forename", namespaces=ns)

            if surname is not None:
                name = ""
                if forename is not None:
                    name += forename.text + " "
                name += surname.text
                authors.append(name)

        references.append({
            "title": title,
            "doi": doi,
            "authors": authors
        })

    return references
