import pytest

from app.services.doi import normalize_doi


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1000/ABC123", "10.1000/abc123"),
        ("https://doi.org/10.1000/ABC123", "10.1000/abc123"),
        ("http://doi.org/10.1000/ABC123", "10.1000/abc123"),
        ("https://dx.doi.org/10.1000/ABC123", "10.1000/abc123"),
        ("http://dx.doi.org/10.1000/ABC123", "10.1000/abc123"),
        ("https://www.doi.org/10.1000/ABC123", "10.1000/abc123"),
        ("doi:10.1000/ABC123", "10.1000/abc123"),
        (" DOI: 10.1000/ABC123. ", "10.1000/abc123"),
        ("<10.1000/ABC123>", "10.1000/abc123"),
        ("10.1000/ABC 123", "10.1000/abc123"),
    ],
)
def test_normalize_doi(value, expected):
    assert normalize_doi(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_normalize_doi_returns_none_for_invalid_input(value):
    assert normalize_doi(value) is None


def test_normalize_doi_preserves_parentheses():
    assert normalize_doi("10.1000/example(2024)") == (
        "10.1000/example(2024)"
    )
