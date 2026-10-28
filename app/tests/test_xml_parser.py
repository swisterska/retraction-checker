
from app.services.xml_parser import extract_references


TEI_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    '<text><listBibl>'
)

TEI_FOOTER = '</listBibl></text></TEI>'


def parse_bibliography(*references):
    """Wrap bibliography entries in a minimal TEI XML document."""
    return extract_references(
        TEI_HEADER + "".join(references) + TEI_FOOTER
    )


def test_extracts_title_doi_authors_and_year():
    xml_reference = """
    <biblStruct>
        <analytic>
            <title>Example research article</title>
            <author>
                <persName>
                    <forename>Jane</forename>
                    <surname>Smith</surname>
                </persName>
            </author>
        </analytic>
        <idno type="DOI">10.1234/example.2024</idno>
        <monogr>
            <imprint>
                <date when="2024-05-10"/>
            </imprint>
        </monogr>
    </biblStruct>
    """

    result = parse_bibliography(xml_reference)

    assert len(result) == 1
    assert result[0]["title"] == "Example research article"
    assert result[0]["doi"] == "10.1234/example.2024"
    assert result[0]["authors"] == ["Jane Smith"]
    assert result[0]["year"] == 2024


def test_extracts_multiple_authors():
    xml_reference = """
    <biblStruct>
        <analytic>
            <title>Collaborative study</title>
            <author>
                <persName>
                    <forename>Jane</forename>
                    <surname>Smith</surname>
                </persName>
            </author>
            <author>
                <persName>
                    <forename>John</forename>
                    <surname>Doe</surname>
                </persName>
            </author>
        </analytic>
    </biblStruct>
    """

    result = parse_bibliography(xml_reference)

    assert result[0]["authors"] == ["Jane Smith", "John Doe"]


def test_returns_none_for_missing_metadata():
    xml_reference = """
    <biblStruct>
        <analytic>
            <title>Article without complete metadata</title>
        </analytic>
    </biblStruct>
    """

    result = parse_bibliography(xml_reference)

    assert result == [{
        "title": "Article without complete metadata",
        "doi": None,
        "authors": [],
        "year": None,
    }]


def test_extracts_doi_using_fallback_regex():
    xml_reference = """
    <biblStruct>
        <analytic>
            <title>Article with DOI in note</title>
            <note>Identifier: 10.1234/fallback-2024</note>
        </analytic>
    </biblStruct>
    """

    result = parse_bibliography(xml_reference)

    assert result[0]["doi"] == "10.1234/fallback-2024"


def test_uses_date_text_when_when_attribute_is_missing():
    xml_reference = """
    <biblStruct>
        <analytic><title>Article with text date</title></analytic>
        <monogr>
            <imprint><date>Published in 2019</date></imprint>
        </monogr>
    </biblStruct>
    """

    result = parse_bibliography(xml_reference)

    assert result[0]["year"] == 2019


def test_returns_empty_list_when_no_references_exist():
    result = parse_bibliography()

    assert result == []
