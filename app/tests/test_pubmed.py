from unittest.mock import patch
from app.services.pubmed import normalize_doi, get_pmid, get_doi_from_crossref


def test_normalize_doi():
    """
    Test that DOI normalization removes common prefixes
    and converts the DOI to lowercase canonical form.
    """

    assert normalize_doi("https://doi.org/10.1000/ABC123") == "10.1000/abc123"
    assert normalize_doi("http://doi.org/10.1000/ABC123") == "10.1000/abc123"
    assert normalize_doi("doi:10.1000/ABC123") == "10.1000/abc123"



@patch("app.services.pubmed.pubmed_search")
def test_get_pmid(mock_search):
    """
    Test that get_pmid correctly returns a PMID when
    PubMed search returns a valid result.
    """

    mock_search.return_value = "123456"

    pmid = get_pmid("10.1000/test")

    assert pmid == "123456"


def test_get_pmid_none():
    """
    Test that get_pmid returns None when DOI input is None.
    """

    pmid = get_pmid(None)

    assert pmid is None




@patch("app.services.pubmed.requests.get")
def test_crossref_doi(mock_get):
    """
    Test that the Crossref API response is correctly parsed
    and the DOI is extracted from the returned JSON structure.
    """

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "message": {
            "items": [
                {"DOI": "10.1234/testdoi"}
            ]
        }
    }

    doi = get_doi_from_crossref("Example title")

    assert doi == "10.1234/testdoi"



@patch("app.services.pubmed.requests.get")
def test_crossref_api_failure(mock_get):
    """
    Test that get_doi_from_crossref returns None when the
    Crossref API returns a non-200 HTTP status code.
    """

    mock_get.return_value.status_code = 500

    doi = get_doi_from_crossref("Example title")

    assert doi is None