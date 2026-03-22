from unittest.mock import patch
from app.services.pubmed import normalize_doi, get_pmid


def test_normalize_doi():
    """
    Test DOI normalization removes prefixes and lowercases value.
    """

    assert normalize_doi("https://doi.org/10.1000/ABC123") == "10.1000/abc123"
    assert normalize_doi("http://doi.org/10.1000/ABC123") == "10.1000/abc123"
    assert normalize_doi("doi:10.1000/ABC123") == "10.1000/abc123"


@patch("app.services.pubmed.pubmed_search")
def test_get_pmid_success(mock_search):
    """
    Test get_pmid returns PMID when PubMed search succeeds.
    """

    mock_search.return_value = "123456"

    pmid = get_pmid("10.1000/test")

    # check if query is exact
    mock_search.assert_called_once_with('"10.1000/test"[DOI]')

    assert pmid == "123456"


def test_get_pmid_none_input():
    """
    Test get_pmid returns None for empty DOI.
    """

    assert get_pmid(None) is None
    assert get_pmid("") is None