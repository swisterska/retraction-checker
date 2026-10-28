
import pandas as pd
import pytest

from app.services.retractions import RetractionService


@pytest.fixture
def retraction_service(tmp_path):
    """Create a temporary Retraction Watch CSV for testing."""

    csv_path = tmp_path / "test_retractions.csv"

    df = pd.DataFrame({
        "OriginalPaperDOI": [
            "10.1002/jcb.23190",
            "10.1000/TEST123",
            None,
        ],
        "Reason": [
            "Investigation by Third Party;Removed;",
            "Unreliable Results;",
            None,
        ],
    })

    df.to_csv(csv_path, index=False)

    return RetractionService(str(csv_path))


def test_is_retracted_returns_true_for_known_doi(retraction_service):
    assert retraction_service.is_retracted("10.1002/jcb.23190") is True


def test_is_retracted_normalizes_doi_url(retraction_service):
    assert retraction_service.is_retracted(
        "https://doi.org/10.1002/jcb.23190"
    ) is True


def test_is_retracted_returns_false_for_unknown_doi(retraction_service):
    assert retraction_service.is_retracted("10.9999/unknown") is False


@pytest.mark.parametrize("doi", [None, "", "   "])
def test_is_retracted_returns_false_for_missing_doi(retraction_service, doi):
    assert retraction_service.is_retracted(doi) is False


def test_get_retraction_reason_returns_reason(retraction_service):
    reason = retraction_service.get_retraction_reason("10.1002/jcb.23190")

    assert reason == "Investigation by Third Party;Removed;"


def test_get_retraction_reason_returns_none_for_unknown_doi(retraction_service):
    assert retraction_service.get_retraction_reason("10.9999/unknown") is None


def test_mark_retracted_adds_status_and_reason(retraction_service):
    references = [
        {"doi": "10.1002/jcb.23190", "title": "Retracted article"},
        {"doi": "10.9999/unknown", "title": "Other article"},
    ]

    result = retraction_service.mark_retracted(references)

    assert result[0]["retracted"] is True
    assert result[0]["retraction_reason"] == "Investigation by Third Party;Removed;"

    assert result[1]["retracted"] is False
    assert result[1]["retraction_reason"] is None


def test_mark_retracted_does_not_modify_original_references(retraction_service):
    references = [{"doi": "10.1002/jcb.23190"}]

    retraction_service.mark_retracted(references)

    assert "retracted" not in references[0]
    assert "retraction_reason" not in references[0]
