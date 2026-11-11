from urllib.error import HTTPError
from unittest.mock import patch

from app.services.pubmed import get_pmid, normalize_doi, pubmed_search


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


@patch("app.services.pubmed.time.sleep")
@patch("app.services.pubmed.Entrez.read")
@patch("app.services.pubmed.Entrez.esearch")
def test_pubmed_search_retries_after_rate_limit(
    mock_esearch,
    mock_read,
    mock_sleep,
):
    """
    PubMed 429 responses should be retried with backoff instead of failing the
    whole analysis.
    """

    mock_esearch.side_effect = [
        HTTPError("https://example.com", 429, "Too Many Requests", hdrs=None, fp=None),
        object(),
    ]
    mock_read.return_value = {"IdList": ["123456"]}

    result = pubmed_search('"10.1000/test"[DOI]')

    assert result == "123456"
    assert mock_esearch.call_count == 2
    assert mock_sleep.call_count >= 1