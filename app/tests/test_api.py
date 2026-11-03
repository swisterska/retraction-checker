
import io

import pytest

from app.database import db
from app.main import create_app
from app.run_grobid_pipeline import process_pdf


@pytest.fixture
def client(monkeypatch):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {
            "users": "sqlite://",
        },
        "MAX_CONTENT_LENGTH": 16 * 1024 * 1024,
        "SECRET_KEY": "test-only-secret-key",
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
        "app.route_modules.documents.process_pdf",
        fake_process_pdf,
    )

    with app.test_client() as test_client:
        csrf_response = test_client.get("/api/csrf")
        assert csrf_response.status_code == 200
        csrf_token = csrf_response.json["csrf_token"]

        register_response = test_client.post(
            "/api/register",
            json={
                "email": "api_test@example.com",
                "password": "StrongTestPassword123!",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert register_response.status_code == 201

        # Logowanie użytkownika.
        login_response = test_client.post(
            "/api/login",
            json={
                "email": "api_test@example.com",
                "password": "StrongTestPassword123!",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert login_response.status_code == 200

        # Po zalogowaniu używamy nowego tokenu CSRF.
        csrf_token = login_response.json["csrf_token"]


        original_open = test_client.open

        def open_with_csrf(*args, **kwargs):
            method = kwargs.get("method", "GET").upper()

            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                headers = dict(kwargs.pop("headers", {}) or {})

                skip_csrf = kwargs.pop("_skip_csrf", False)

                if not skip_csrf:
                    headers.setdefault("X-CSRF-Token", csrf_token)

                kwargs["headers"] = headers

            return original_open(*args, **kwargs)

        test_client.open = open_with_csrf


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
        data={
            "file": (
                io.BytesIO(b"some content"),
                "document.txt",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["message"] == "Only PDF files are allowed."


def test_analyze_returns_400_for_invalid_pdf_content(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"This is not a PDF"),
                "document.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert (
        "does not appear to be a valid PDF"
        in response.json["message"]
    )


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
    oversized_content = (
        b"%PDF-1.7\n" + b"x" * (16 * 1024 * 1024)
    )

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


def test_analyze_requires_authentication(monkeypatch):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {"users": "sqlite://"},
        "SECRET_KEY": "test-only-secret-key",
    })

    with app.test_client() as test_client:
        csrf_response = test_client.get("/api/csrf")
        assert csrf_response.status_code == 200
        csrf_token = csrf_response.json["csrf_token"]

        response = test_client.post(
            "/api/analyze",
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code == 401
    assert response.json["message"] == "Authentication required."


def test_csrf_token_is_required_for_post(client):
    response = client.post(
        "/api/logout",
        headers={"X-CSRF-Token": "invalid-token"},
    )

    assert response.status_code == 400
    assert "CSRF token" in response.json["message"]


def test_csrf_token_is_missing_for_post(client):
    response = client.post(
        "/api/logout",
        headers={},
        _skip_csrf=True,
    )

    assert response.status_code == 400
    assert "CSRF token" in response.json["message"]

def test_logout_clears_authentication(client):
    response = client.post("/api/logout")

    assert response.status_code == 200
    assert response.json["status"] == "success"

    me_response = client.get("/api/me")

    assert me_response.status_code == 401


def test_current_user_endpoint(client):
    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert response.json["user"]["email"] == "api_test@example.com"


def test_user_cannot_access_another_users_document(client):
    upload_response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"%PDF-1.7\nfake test PDF content"),
                "private_document.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert upload_response.status_code == 200
    document_id = upload_response.json["document_id"]

    owner_response = client.get(
        f"/api/documents/{document_id}/results"
    )
    assert owner_response.status_code == 200

    register_response = client.post(
        "/api/register",
        json={
            "email": "second_user@example.com",
            "password": "AnotherStrongPassword123!",
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/api/login",
        json={
            "email": "second_user@example.com",
            "password": "AnotherStrongPassword123!",
        },
    )
    assert login_response.status_code == 200

    other_user_results = client.get(
        f"/api/documents/{document_id}/results"
    )
    assert other_user_results.status_code == 404
    assert other_user_results.json["message"] == "Document not found."

    other_user_documents = client.get("/api/documents")
    assert other_user_documents.status_code == 200
    assert other_user_documents.json["total_documents"] == 0
    assert other_user_documents.json["documents"] == []


def test_document_endpoints_use_bounded_number_of_queries(client):
    from sqlalchemy import event

    from app.database import db
    from app.services.database_service import save_analysis_results

    app = client.application

    with client.session_transaction() as session:
        user_id = session["user_id"]

    # Create multiple documents with multiple references.
    with app.app_context():
        document_ids = []

        for document_number in range(5):
            references = []

            for reference_number in range(10):
                references.append({
                    "title": (
                        f"Publication {document_number}-{reference_number}"
                    ),
                    "authors": ["Test Author"],
                    "doi": (
                        f"10.1000/test-{document_number}-{reference_number}"
                    ),
                    "pmid": None,
                    "retracted": (
                        document_number == 0 and reference_number == 0
                    ),
                    "retraction_reason": (
                        "Test retraction reason"
                        if document_number == 0 and reference_number == 0
                        else None
                    ),
                })

            document_id = save_analysis_results(
                user_id=user_id,
                filename=f"document_{document_number}.pdf",
                references=references,
            )
            document_ids.append(document_id)

        engine = db.engine

    query_count = {"selects": 0}

    def count_selects(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        if statement.lstrip().upper().startswith("SELECT"):
            query_count["selects"] += 1

    event.listen(engine, "before_cursor_execute", count_selects)

    try:
        # Measure document history.
        response = client.get("/api/documents")

        assert response.status_code == 200
        assert response.json["total_documents"] == 5

        history_queries = query_count["selects"]

        # Measure one document's results.
        query_count["selects"] = 0

        response = client.get(
            f"/api/documents/{document_ids[0]}/results"
        )

        assert response.status_code == 200
        assert response.json["total_references"] == 10

        results_queries = query_count["selects"]

    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            count_selects,
        )

    # The number of queries must not grow with the number of documents or references.
    assert history_queries <= 3, (
        f"Document history executed {history_queries} SELECT queries."
    )

    assert results_queries <= 4, (
        f"Document results executed {results_queries} SELECT queries."
    )


def test_full_analysis_pipeline_integration(client, monkeypatch, tmp_path):
    """
    Integration test:
    PDF upload -> GROBID -> XML parser -> PubMed
    -> Retraction Watch -> database -> results API.
    """

    from app.models import (
        UploadedDocument,
        ExtractedReference,
        DetectionResult,
    )
    from app.services import grobid, pubmed
    from app import run_grobid_pipeline

    # Controlled TEI XML returned by mocked GROBID.
    tei_xml = """
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
        <text>
            <listBibl>
                <biblStruct>
                    <analytic>
                        <title>Retracted integration test article</title>
                        <author>
                            <persName>
                                <forename>Jane</forename>
                                <surname>Smith</surname>
                            </persName>
                        </author>
                    </analytic>
                    <idno type="DOI">10.1002/jcb.23190</idno>
                    <monogr>
                        <imprint>
                            <date when="2020"/>
                        </imprint>
                    </monogr>
                </biblStruct>

                <biblStruct>
                    <analytic>
                        <title>Valid integration test article</title>
                        <author>
                            <persName>
                                <forename>John</forename>
                                <surname>Doe</surname>
                            </persName>
                        </author>
                    </analytic>
                    <idno type="DOI">10.1234/example</idno>
                    <monogr>
                        <imprint>
                            <date when="2021"/>
                        </imprint>
                    </monogr>
                </biblStruct>
            </listBibl>
        </text>
    </TEI>
    """

    # Create a controlled Retraction Watch CSV.
    csv_path = tmp_path / "retractions.csv"

    csv_path.write_text(
        "OriginalPaperDOI,Reason\n"
        "10.1002/jcb.23190,Investigation by Third Party\n",
        encoding="utf-8",
    )

    # Mock only the external GROBID HTTP request.
    class FakeResponse:
        text = tei_xml

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        grobid.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )

        # Mock PubMed results.
    from app import run_grobid_pipeline

    pmid_mapping = {
        "10.1002/jcb.23190": "12345678",
        "10.1234/example": "87654321",
    }

    monkeypatch.setattr(
        pubmed,
        "get_pmid",
        lambda doi: pmid_mapping.get(doi),
    )

    monkeypatch.setattr(
        pubmed,
        "get_pmid_by_title",
        lambda title: None,
    )

    # Avoid real network requests and use the controlled CSV.
    monkeypatch.setattr(
        run_grobid_pipeline,
        "ensure_retractions_dataset",
        lambda *args, **kwargs: False,
    )

    # Point the actual pipeline to our test dataset.
    monkeypatch.setattr(
        run_grobid_pipeline,
        "CSV_PATH",
        str(csv_path),
    )

    # Make the API endpoint use the real analysis pipeline.
    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        run_grobid_pipeline.process_pdf,
    )

    # Upload a PDF through the real API endpoint.
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                __import__("io").BytesIO(
                    b"%PDF-1.7\nIntegration test PDF"
                ),
                "integration_test.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert response.json["references_processed"] == 2
    assert response.json["retracted_references"] == 1

    document_id = response.json["document_id"]

    # Verify database persistence.
    document = db.session.get(
        UploadedDocument,
        document_id,
    )

    assert document is not None
    assert document.filename == "integration_test.pdf"
    assert document.processing_status == "completed"

    references = (
        ExtractedReference.query
        .filter_by(document_id=document_id)
        .order_by(ExtractedReference.id)
        .all()
    )

    assert len(references) == 2

    assert references[0].doi == "10.1002/jcb.23190"
    assert references[0].pmid == "12345678"

    assert references[1].doi == "10.1234/example"
    assert references[1].pmid == "87654321"

    detections = [
        detection
        for reference in references
        for detection in reference.detection_results
    ]

    assert len(detections) == 2
    assert sum(
        1 for detection in detections if detection.is_retracted
    ) == 1

    # Verify the public results endpoint.
    results_response = client.get(
        f"/api/documents/{document_id}/results"
    )

    assert results_response.status_code == 200
    assert results_response.json["total_references"] == 2
    assert results_response.json["retracted_references"] == 1

    first_result = results_response.json["results"][0]

    assert first_result["doi"] == "10.1002/jcb.23190"
    assert first_result["pmid"] == "12345678"
    assert first_result["is_retracted"] is True


def test_register_rejects_invalid_email(client):
    response = client.post(
        "/api/register",
        json={
            "email": "invalid-email",
            "password": "StrongTestPassword123!",
        },
    )

    assert response.status_code == 400
    assert response.json["status"] == "error"


def test_register_rejects_short_password(client):
    response = client.post(
        "/api/register",
        json={
            "email": "short_password@example.com",
            "password": "short",
        },
    )

    assert response.status_code == 400
    assert response.json["status"] == "error"


def test_register_rejects_duplicate_email(client):
    response = client.post(
        "/api/register",
        json={
            "email": "api_test@example.com",
            "password": "StrongTestPassword123!",
        },
    )

    assert response.status_code == 400
    assert response.json["status"] == "error"


def test_login_rejects_incorrect_password(client):
    response = client.post(
        "/api/login",
        json={
            "email": "api_test@example.com",
            "password": "IncorrectPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json["status"] == "error"
    assert response.json["message"] == "Invalid email or password."


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/api/login",
        json={
            "email": "unknown@example.com",
            "password": "StrongTestPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json["status"] == "error"
    assert response.json["message"] == "Invalid email or password."

def test_analyze_rejects_non_pdf_extension(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"Some text content"),
                "document.txt",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "Only PDF files are allowed." in response.json["message"]


def test_analyze_rejects_empty_file(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b""),
                "empty.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "valid PDF" in response.json["message"]


def test_login_rate_limit_returns_429(client):
    responses = []

    for _ in range(6):
        response = client.post(
            "/api/login",
            json={
                "email": "api_test@example.com",
                "password": "IncorrectPassword123!",
            },
        )
        responses.append(response.status_code)

    # The client fixture performs one successful login during setup.
    # That request also counts toward the rate limit.
    assert responses[:4] == [401, 401, 401, 401]
    assert responses[4:] == [429, 429]

def test_register_rate_limit_returns_429(client):
    from app.main import limiter

    limiter.reset()

    responses = []

    for index in range(6):
        response = client.post(
            "/api/register",
            json={
                "email": f"ratelimit{index}@example.com",
                "password": "StrongTestPassword123!",
            },
        )
        responses.append(response.status_code)

    assert responses[:5] == [201, 201, 201, 201, 201]
    assert responses[5] == 429