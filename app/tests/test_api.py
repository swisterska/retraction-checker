
import io

import pytest

from app.database import db
from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,
    })

    with app.app_context():
        db.create_all()

    def fake_process_pdf(pdf_path):
        return [
            {
                "title": "Retracted test publication",
                "authors": ["Test Author"],
                "year": 2020,
                "doi": "10.1002/jcb.23190",
                "pmid": None,
                "retracted": True,
                "retraction_reason": "Investigation by Third Party;Removed;",
            },
            {
                "title": "Non-retracted test publication",
                "authors": ["Another Author"],
                "year": 2021,
                "doi": "10.1234/example",
                "pmid": None,
                "retracted": False,
                "retraction_reason": None,
            },
        ]

    monkeypatch.setattr(
        "app.routes.process_pdf",
        fake_process_pdf,
    )

    with app.test_client() as test_client:
        yield test_client

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_analyze_returns_400_when_file_is_missing(client):
    response = client.post("/api/analyze")

    assert response.status_code == 400
    assert response.json["status"] == "error"
    assert "No file provided" in response.json["message"]


def test_analyze_returns_400_for_non_pdf_extension(client):
    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(b"some content"), "document.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["message"] == "Only PDF files are allowed."


def test_analyze_returns_400_for_invalid_pdf_content(client):
    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(b"This is not a PDF"), "document.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "does not appear to be a valid PDF" in response.json["message"]


def test_analyze_saves_results_for_valid_pdf(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"%PDF-1.7\nfake test PDF content"),
                "test.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert response.json["filename"] == "test.pdf"
    assert response.json["references_processed"] == 2
    assert response.json["retracted_references"] == 1

    document_id = response.json["document_id"]

    results_response = client.get(
        f"/api/documents/{document_id}/results"
    )

    assert results_response.status_code == 200
    assert results_response.json["total_references"] == 2
    assert results_response.json["retracted_references"] == 1


def test_documents_history_includes_analyzed_document(client):
    upload_response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"%PDF-1.7\nfake test PDF content"),
                "history_test.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert upload_response.status_code == 200

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert response.json["total_documents"] == 1

    document = response.json["documents"][0]
    assert document["filename"] == "history_test.pdf"
    assert document["total_references"] == 2
    assert document["retracted_references"] == 1


def test_retracted_only_filter_returns_only_retracted_references(client):
    upload_response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"%PDF-1.7\nfake test PDF content"),
                "filter_test.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert upload_response.status_code == 200
    document_id = upload_response.json["document_id"]

    response = client.get(
        f"/api/documents/{document_id}/results?retracted_only=true"
    )

    assert response.status_code == 200
    assert response.json["total_references"] == 1
    assert response.json["retracted_references"] == 1

    reference = response.json["results"][0]
    assert reference["doi"] == "10.1002/jcb.23190"
    assert reference["is_retracted"] is True


def test_results_returns_404_for_unknown_document(client):
    response = client.get("/api/documents/999999/results")

    assert response.status_code == 404
    assert response.json["status"] == "error"
    assert response.json["message"] == "Document not found."



def test_analyze_returns_413_for_oversized_request(client):
    oversized_content = b"%PDF-1.7\n" + b"x" * (16 * 1024 * 1024)

    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(oversized_content),
                "large_document.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 413
    assert response.json["status"] == "error"
    assert "too large" in response.json["message"].lower()

