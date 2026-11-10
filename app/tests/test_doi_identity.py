from unittest.mock import Mock

import requests

from app.services import doi_identity


def test_titles_match_ignores_case_and_punctuation():
    assert doi_identity.titles_match(
        "A Study of Cells: Results and Methods",
        "A study of cells - results and methods.",
    )


def test_titles_match_rejects_a_different_work():
    assert not doi_identity.titles_match(
        "A Study of Cells",
        "A Study of Machine Learning",
    )


def test_titles_match_retraction_prefix_in_resolved_metadata():
    assert doi_identity.titles_match(
        "Genistein protects genioglossus myocyte against hypoxia-induced injury through PI3K-Akt and ERK MAPK pathways",
        "Retraction: Genistein protects genioglossus myocyte against hypoxia-induced injury through PI3K-Akt and ERK MAPK pathways",
    )


def test_verify_doi_identity_accepts_matching_resolved_metadata(monkeypatch):
    monkeypatch.setattr(
        doi_identity,
        "get_doi_metadata",
        lambda _doi: {
            "DOI": "10.1000/example",
            "title": ["A Study of Cells"],
        "author": [{"family": "Smith"}],
        },
    )

    assert doi_identity.verify_doi_identity(
        "https://doi.org/10.1000/EXAMPLE",
        "A Study of Cells",
        ["J. Smith"],
    ) == (True, None)


def test_verify_doi_identity_rejects_a_valid_but_wrong_doi(monkeypatch):
    monkeypatch.setattr(
        doi_identity,
        "get_doi_metadata",
        lambda _doi: {
            "DOI": "10.1000/other-work",
            "title": ["Another Publication"],
        },
    )

    verified, note = doi_identity.verify_doi_identity(
        "10.1000/other-work",
        "The Cited Publication",
    )

    assert verified is False
    assert "does not match" in note


def test_verify_doi_identity_checks_first_author_when_available(monkeypatch):
    monkeypatch.setattr(
        doi_identity,
        "get_doi_metadata",
        lambda _doi: {
            "DOI": "10.1000/example",
            "title": ["A Study of Cells"],
            "author": [{"family": "Jones"}],
        },
    )

    verified, note = doi_identity.verify_doi_identity(
        "10.1000/example",
        "A Study of Cells",
        ["J. Smith"],
    )

    assert verified is False
    assert "first author" in note


def test_verify_doi_identity_does_not_verify_when_metadata_is_unavailable(monkeypatch):
    monkeypatch.setattr(doi_identity, "get_doi_metadata", lambda _doi: None)

    verified, note = doi_identity.verify_doi_identity(
        "10.1000/unavailable",
        "A Study of Cells",
    )

    assert verified is False
    assert "could not be retrieved" in note


def test_get_doi_metadata_uses_doi_content_negotiation(monkeypatch):
    response = Mock()
    response.json.return_value = {"DOI": "10.1000/example", "title": ["Example"]}
    monkeypatch.setattr(doi_identity.requests, "get", lambda *args, **kwargs: response)

    metadata = doi_identity.get_doi_metadata("10.1000/example")

    assert metadata["DOI"] == "10.1000/example"
    response.raise_for_status.assert_called_once_with()
    assert response.json.call_count == 1


def test_doi_lookup_network_error_is_a_safe_not_verified_result(monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(doi_identity.requests, "get", fail)

    assert doi_identity.get_doi_metadata("10.1000/example") is None


def test_doi_not_found_has_a_specific_verification_note(monkeypatch):
    response = Mock(status_code=404)
    monkeypatch.setattr(doi_identity.requests, "get", lambda *args, **kwargs: response)

    verified, note = doi_identity.verify_doi_identity(
        "10.1000/not-registered",
        "A Study of Cells",
    )

    assert verified is False
    assert "was not found" in note


def test_batch_verification_reuses_metadata_for_duplicate_dois(monkeypatch):
    calls = []

    def fake_lookup(doi):
        calls.append(doi)
        return {"DOI": doi, "title": ["A Study of Cells"]}

    monkeypatch.setattr(doi_identity, "get_doi_metadata", fake_lookup)
    results = doi_identity.verify_references_doi_identity([
        {"doi": "10.1000/example", "title": "A Study of Cells"},
        {"doi": "https://doi.org/10.1000/EXAMPLE", "title": "A Study of Cells"},
    ])

    assert calls == ["10.1000/example"]
    assert [item["doi_identity_verified"] for item in results] == [True, True]
