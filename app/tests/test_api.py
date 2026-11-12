
import io
import sys
from pathlib import Path

import pytest

from app.database import db
from app.main import create_app


VALID_PDF_PATH = Path(__file__).parent / "fixtures" / "testychat.pdf"


def valid_pdf_bytes():
    return VALID_PDF_PATH.read_bytes()


def switch_to_guest(client):
    logout_response = client.post("/api/logout")
    assert logout_response.status_code == 200
    return client.get("/api/csrf").json["csrf_token"]


def test_main_starts_analysis_worker_when_run_as_script(monkeypatch):
    import app.main as app_main

    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(app_main.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("AUTO_START_ANALYSIS_WORKER", "true")

    app_main.start_analysis_worker()

    assert captured["command"][:3] == [sys.executable, "-m", "app.analysis_worker"]
    assert captured["kwargs"]["start_new_session"] is True


def test_main_stops_worker_if_server_cannot_start(monkeypatch):
    import app.main as app_main

    class FakeWorker:
        terminated = False
        waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.waited = timeout == 10

    class FakeApp:
        def run(self, **_kwargs):
            raise OSError("port already in use")

    worker = FakeWorker()
    monkeypatch.setattr(app_main, "start_analysis_worker", lambda: worker)

    with pytest.raises(OSError, match="port already in use"):
        app_main.run_server(FakeApp(), 5003)

    assert worker.terminated is True
    assert worker.waited is True


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.route_modules.auth.send_verification_email",
        lambda _email, _token: None,
    )
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {
            "users": "sqlite://",
        },
        "MAX_UPLOAD_SIZE_BYTES": 16 * 1024 * 1024,
        "MAX_CONTENT_LENGTH": (16 * 1024 * 1024) + (64 * 1024),
        "ANALYSIS_UPLOAD_DIR": str(tmp_path / "queued-uploads"),
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
                "verification_status": "retracted",
                "retraction_reason": "Investigation by Third Party;Removed;",
            },
            {
                "title": "Non-retracted test publication",
                "authors": ["Another Author"],
                "year": 2021,
                "doi": "10.1234/example",
                "pmid": None,
                "retracted": False,
                "verification_status": "verified",
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
        from app.models import User
        verified_user = User.query.filter_by(email="api_test@example.com").one()
        verified_user.email_verified = True
        db.session.commit()

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


def test_document_refresh_requires_valid_csrf_token(client, monkeypatch):
    monkeypatch.setattr(
        "app.route_modules.documents.ensure_retractions_dataset",
        lambda *args, **kwargs: True,
    )

    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
                "document.pdf",
            )
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    document_id = response.json["document_id"]
    added_response = client.get(
        f"/api/documents/{document_id}/results"
    )
    added_at = added_response.json["document"]["upload_date"]
    assert added_at
    assert added_response.json["document"]["last_checked_at"]

    missing_token_response = client.post(
        f"/api/documents/{document_id}/refresh",
        _skip_csrf=True,
    )
    assert missing_token_response.status_code == 400
    assert "CSRF" in missing_token_response.json["message"]

    refresh_response = client.post(f"/api/documents/{document_id}/refresh")

    assert refresh_response.status_code == 200
    assert refresh_response.json["status"] == "success"
    assert refresh_response.json["document_id"] == document_id
    assert refresh_response.json["last_checked_at"]
    updated_report = client.get(
        f"/api/documents/{document_id}/results"
    ).json
    assert updated_report["document"]["upload_date"] == added_at
    assert updated_report["document"]["last_checked_at"] == refresh_response.json["last_checked_at"]


def test_watchlist_is_persisted_per_user_and_visible_in_document_list(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
                "watch.pdf",
            )
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    document_id = response.json["document_id"]

    add_watch_response = client.post(f"/api/documents/{document_id}/watch")
    assert add_watch_response.status_code == 200
    assert add_watch_response.json["watched"] is True

    watchlist_response = client.get("/api/documents/watchlist")
    assert watchlist_response.status_code == 200
    assert watchlist_response.json["watchlist"] == [document_id]

    list_response = client.get("/api/documents")
    assert list_response.status_code == 200
    item = next(doc for doc in list_response.json["documents"] if doc["id"] == document_id)
    assert item["is_watched"] is True

    remove_watch_response = client.delete(f"/api/documents/{document_id}/watch")
    assert remove_watch_response.status_code == 200
    assert remove_watch_response.json["watched"] is False

    refreshed_watchlist = client.get("/api/documents/watchlist")
    assert refreshed_watchlist.status_code == 200
    assert refreshed_watchlist.json["watchlist"] == []


def test_list_documents_keeps_same_filename_uploads_as_distinct_documents(client):
    first = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
                "test.pdf",
            )
        },
        content_type="multipart/form-data",
    )
    second = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
                "test.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get("/api/documents")

    assert response.status_code == 200
    assert len(response.json["documents"]) == 2
    assert {item["filename"] for item in response.json["documents"]} == {"test.pdf"}


def test_password_reset_email_and_token_flow_work(client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "app.route_modules.auth.send_password_reset_email",
        lambda recipient, token: captured.append((recipient, token)),
    )

    response = client.post(
        "/api/forgot-password",
        json={"email": "api_test@example.com"},
    )
    assert response.status_code == 200
    assert response.json["status"] == "success"
    assert len(captured) == 1
    assert captured[0][0] == "api_test@example.com"

    token = captured[0][1]
    reset_response = client.post(
        "/api/reset-password",
        json={"token": token, "password": "FreshPassword123!"},
    )
    assert reset_response.status_code == 200
    assert reset_response.json["status"] == "success"


def test_account_management_routes_require_password_and_clear_history(client):
    create_document = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
                "history.pdf",
            )
        },
        content_type="multipart/form-data",
    )
    assert create_document.status_code == 200

    wrong_password = client.post(
        "/api/account/password",
        json={
            "current_password": "WrongPassword123!",
            "new_password": "NewPassword456!",
        },
    )
    assert wrong_password.status_code == 401

    change_email = client.post(
        "/api/account/email",
        json={
            "current_password": "StrongTestPassword123!",
            "new_email": "updated_api_test@example.com",
        },
    )
    assert change_email.status_code == 200
    assert change_email.json["status"] == "success"

    change_password = client.post(
        "/api/account/password",
        json={
            "current_password": "StrongTestPassword123!",
            "new_password": "UpdatedPassword456!",
        },
    )
    assert change_password.status_code == 200
    assert change_password.json["status"] == "success"

    clear_history = client.post(
        "/api/account/clear-history",
        json={"current_password": "UpdatedPassword456!"},
    )
    assert clear_history.status_code == 200
    assert clear_history.json["status"] == "success"

    documents = client.get("/api/documents")
    assert documents.status_code == 200
    assert documents.json["total_documents"] == 0

    delete_account = client.delete(
        "/api/account",
        json={"current_password": "UpdatedPassword456!"},
    )
    assert delete_account.status_code == 200
    assert delete_account.json["status"] == "success"

    me = client.get("/api/me")
    assert me.status_code == 401


def test_analyze_returns_400_when_file_is_missing(client):
    response = client.post("/api/analyze")

    assert response.status_code == 400
    assert response.json["status"] == "error"
    assert response.json["code"] == "FILE_MISSING"


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
    assert response.json["code"] == "INVALID_FILE_FORMAT"
    assert response.json["message"] == (
        "This file is not a PDF. Rename it so it ends with .pdf and try again."
    )


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
    assert response.json["code"] == "INVALID_FILE_FORMAT"


def test_analyze_rejects_corrupted_pdf_before_analysis(client, monkeypatch):
    def should_not_analyze(_pdf_path):
        raise AssertionError("Corrupted PDFs must be rejected before analysis")

    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        should_not_analyze,
    )

    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(b"%PDF-1.7\nnot a readable PDF structure"),
                "corrupted.pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.json["code"] == "PDF_CORRUPTED"
    assert response.json["message"] == (
        "The PDF file appears to be corrupted or unreadable."
    )


def test_analyze_rejects_pdf_without_readable_text(client, monkeypatch):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    pdf_stream = io.BytesIO()
    writer.write(pdf_stream)
    pdf_stream.seek(0)

    def should_not_analyze(_pdf_path):
        raise AssertionError("Textless PDFs must be rejected before analysis")

    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        should_not_analyze,
    )

    response = client.post(
        "/api/analyze",
        data={"file": (pdf_stream, "no_text.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.json["code"] == "NO_READABLE_TEXT"
    assert response.json["message"] == (
        "No readable text was found in this document."
    )


def test_analyze_maps_grobid_failure_to_service_unavailable(client, monkeypatch):
    from app.services.grobid import GrobidServiceError

    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        lambda _path: (_ for _ in ()).throw(
            GrobidServiceError("internal GROBID timeout detail")
        ),
    )

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "grobid.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.json["code"] == "REFERENCE_EXTRACTION_UNAVAILABLE"
    assert response.json["message"] == (
        "Reference extraction is temporarily unavailable. Please try again later."
    )
    assert "internal GROBID timeout detail" not in response.get_data(as_text=True)


def test_analyze_maps_missing_retraction_dataset_to_service_unavailable(
    client,
    monkeypatch,
):
    from app.services.retractions import RetractionDataError

    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        lambda _path: (_ for _ in ()).throw(
            RetractionDataError("internal dataset detail")
        ),
    )

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "retractions.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert response.json["code"] == "RETRACTION_DATA_UNAVAILABLE"
    assert "internal dataset detail" not in response.get_data(as_text=True)


def test_analyze_maps_database_error_to_safe_response(client, monkeypatch, caplog):
    from sqlalchemy.exc import SQLAlchemyError

    def fail_to_save(**_kwargs):
        raise SQLAlchemyError("simulated private database detail")

    monkeypatch.setattr(
        "app.route_modules.documents.save_analysis_results",
        fail_to_save,
    )

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "database.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.json["code"] == "DATABASE_SAVE_FAILED"
    assert response.json["message"] == (
        "The document could not be processed. Please try again."
    )
    assert "simulated private database detail" not in response.get_data(as_text=True)
    assert "simulated private database detail" in caplog.text


def test_analyze_maps_unexpected_error_to_safe_response(client, monkeypatch):
    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        lambda _path: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "unexpected.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 500
    assert response.json["code"] == "ANALYSIS_FAILED"
    assert response.json["message"] == (
        "The document could not be processed. Please try again."
    )
    assert "private detail" not in response.get_data(as_text=True)


def test_analyze_reports_when_no_references_are_found(client, monkeypatch):
    monkeypatch.setattr(
        "app.route_modules.documents.process_pdf",
        lambda _path: [],
    )

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "no_refs.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.json["code"] == "NO_REFERENCES_FOUND"


def test_analyze_saves_results_for_valid_pdf(client):
    response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
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
    assert results_response.json["results"][0]["verification_status"] == "retracted"
    assert results_response.json["results"][1]["verification_status"] == "verified"


def test_documents_history_includes_analyzed_document(client):
    upload_response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
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


def test_delete_document_cascades_analysis_but_preserves_publication_and_notification(
    client,
):
    from app.models import (
        DetectionResult,
        ExtractedReference,
        Notification,
        RetractedPublication,
        UploadedDocument,
    )

    upload_response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "delete_me.pdf")},
        content_type="multipart/form-data",
    )
    document_id = upload_response.json["document_id"]
    with client.session_transaction() as session:
        user_id = session["user_id"]

    app = client.application
    with app.app_context():
        notification = Notification(
            user_id=user_id,
            document_id=document_id,
            message="An analysis notification",
        )
        db.session.add(notification)
        db.session.commit()
        publication_count = RetractedPublication.query.count()

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 200
    assert response.json["status"] == "success"

    with app.app_context():
        assert db.session.get(UploadedDocument, document_id) is None
        assert ExtractedReference.query.filter_by(
            document_id=document_id,
        ).count() == 0
        assert DetectionResult.query.count() == 0
        saved_notification = Notification.query.one()
        assert saved_notification.document_id is None
        assert RetractedPublication.query.count() == publication_count


def test_user_cannot_delete_another_users_document(client):
    from app.models import UploadedDocument, User

    app = client.application
    with app.app_context():
        other_user = User(
            email="delete_owner@example.com",
            password_hash="test_hash_not_for_real_login",
        )
        db.session.add(other_user)
        db.session.flush()
        document = UploadedDocument(
            user_id=other_user.id,
            filename="another_users_document.pdf",
            processing_status="completed",
        )
        db.session.add(document)
        db.session.commit()
        document_id = document.id

    response = client.delete(f"/api/documents/{document_id}")

    assert response.status_code == 404
    assert response.json["code"] == "DOCUMENT_NOT_FOUND"
    with app.app_context():
        assert db.session.get(UploadedDocument, document_id) is not None


def test_guest_can_analyze_and_open_session_only_temporary_report(client):
    csrf_token = switch_to_guest(client)
    upload_response = client.post(
        "/api/guest/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "guest.pdf")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )

    assert upload_response.status_code == 200
    assert upload_response.json["references_processed"] == 2
    report_id = upload_response.json["report_id"]

    report_response = client.get(f"/api/guest/reports/{report_id}")
    assert report_response.status_code == 200
    assert report_response.json["document"]["filename"] == "guest.pdf"
    assert report_response.json["results"][0]["verification_status"] == "retracted"

    other_client = client.application.test_client()
    other_response = other_client.get(f"/api/guest/reports/{report_id}")
    assert other_response.status_code == 404
    assert other_response.json["code"] == "GUEST_REPORT_NOT_FOUND"

    from app.models import UploadedDocument

    with client.application.app_context():
        assert UploadedDocument.query.count() == 0


def test_guest_session_can_analyze_only_once_until_report_expires(client):
    csrf_token = switch_to_guest(client)
    first_response = client.post(
        "/api/guest/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "first.pdf")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    second_response = client.post(
        "/api/guest/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "second.pdf")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json["code"] == "GUEST_SESSION_LIMIT"


def test_async_analysis_is_queued_and_worker_finishes_it(client, monkeypatch):
    from app import analysis_worker
    from app.models import AnalysisJob, UploadedDocument

    def should_not_run_in_request(_path):
        raise AssertionError("The request must enqueue work, not analyze the PDF")

    monkeypatch.setattr("app.route_modules.documents.process_pdf", should_not_run_in_request)
    response = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "queued.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    assert response.json["status"] == "queued"
    job_id = response.json["job_id"]
    assert client.get("/api/jobs").json["jobs"][0]["job_id"] == job_id

    monkeypatch.setattr(
        "app.analysis_worker.process_pdf",
        lambda _path: [
            {"title": "Example", "authors": ["A. Author"], "year": 2024,
             "doi": "10.1234/example", "retracted": False,
             "verification_status": "verified"}
        ],
    )
    monkeypatch.setattr("app.analysis_worker.send_ready_email", lambda _job: None)
    assert analysis_worker.process_next_job(client.application)
    with client.application.app_context():
        job = db.session.get(AnalysisJob, job_id)
        assert job.status == "completed"
        assert job.email_sent is True
        assert UploadedDocument.query.filter_by(id=job.document_id).first() is not None


def test_analyze_drains_queued_jobs_before_processing_new_upload(client, monkeypatch):
    from app import analysis_worker
    from app.models import AnalysisJob

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "queued-first.pdf")},
        content_type="multipart/form-data",
    )
    assert queued.status_code == 202
    queued_id = queued.json["job_id"]

    monkeypatch.setattr(
        "app.analysis_worker.process_pdf",
        lambda _path: [
            {"title": "Queued result", "authors": ["Queued Author"], "year": 2024,
             "doi": "10.1234/queued", "retracted": False,
             "verification_status": "verified"}
        ],
    )
    monkeypatch.setattr("app.analysis_worker.send_ready_email", lambda _job: None)

    response = client.post(
        "/api/analyze",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "fresh.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["references_processed"] == 2
    with client.application.app_context():
        job = db.session.get(AnalysisJob, queued_id)
        assert job.status == "completed"
        assert job.document_id is not None


def test_guest_background_job_requires_email_and_email_link_opens_report(client):
    from app.services.analysis_jobs import guest_access_token

    csrf_token = switch_to_guest(client)
    missing_email = client.post(
        "/api/guest/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "guest.pdf")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert missing_email.status_code == 400
    assert missing_email.json["code"] == "EMAIL_REQUIRED"

    queued = client.post(
        "/api/guest/jobs",
        data={"email": "reader@example.org", "file": (io.BytesIO(valid_pdf_bytes()), "guest.pdf")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert queued.status_code == 202
    job_id = queued.json["report_id"]
    assert client.get(f"/api/guest/reports/{job_id}").json["status"] == "queued"

    with client.application.app_context():
        access = guest_access_token(job_id)
    other_browser = client.application.test_client()
    assert other_browser.get(f"/api/guest/reports/{job_id}").status_code == 404
    allowed = other_browser.get(f"/api/guest/reports/{job_id}?access={access}")
    assert allowed.status_code == 200
    assert allowed.json["status"] == "queued"


def test_failed_jobs_remain_visible_to_the_user(client, monkeypatch):
    from app.models import AnalysisJob

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "failed-job.pdf")},
        content_type="multipart/form-data",
    )
    assert queued.status_code == 202
    job_id = queued.json["job_id"]

    with client.application.app_context():
        job = db.session.get(AnalysisJob, job_id)
        job.status = "failed"
        job.error_code = "GROBID_EMPTY_RESPONSE"
        db.session.commit()

    jobs = client.get("/api/jobs").json["jobs"]
    failed = next(item for item in jobs if item["job_id"] == job_id)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "GROBID_EMPTY_RESPONSE"


def test_failed_job_can_be_dismissed(client):
    from app.models import AnalysisJob

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "dismiss-me.pdf")},
        content_type="multipart/form-data",
    )
    job_id = queued.json["job_id"]
    with client.application.app_context():
        job = db.session.get(AnalysisJob, job_id)
        job.status = "failed"
        job.error_code = "ANALYSIS_FAILED"
        db.session.commit()
    csrf_token = client.get("/api/csrf").json["csrf_token"]
    deleted = client.delete(f"/api/jobs/{job_id}", headers={"X-CSRF-Token": csrf_token})
    assert deleted.status_code == 200
    assert all(item["job_id"] != job_id for item in client.get("/api/jobs").json["jobs"])


def test_guest_limit_is_per_email_for_24_hours_and_allows_another_email(client):
    csrf_token = switch_to_guest(client)
    first = client.post(
        "/api/guest/jobs",
        data={"email": "first@example.org", "file": (io.BytesIO(valid_pdf_bytes()), "one.pdf")},
        headers={"X-CSRF-Token": csrf_token}, content_type="multipart/form-data",
    )
    different_email = client.post(
        "/api/guest/jobs",
        data={"email": "second@example.org", "file": (io.BytesIO(valid_pdf_bytes()), "two.pdf")},
        headers={"X-CSRF-Token": csrf_token}, content_type="multipart/form-data",
    )
    repeated_email = client.post(
        "/api/guest/jobs",
        data={"email": "FIRST@example.org", "file": (io.BytesIO(valid_pdf_bytes()), "three.pdf")},
        headers={"X-CSRF-Token": csrf_token}, content_type="multipart/form-data",
    )
    assert first.status_code == 202
    assert different_email.status_code == 202
    assert repeated_email.status_code == 429
    assert repeated_email.json["code"] == "GUEST_ANALYSIS_IN_PROGRESS"
    assert repeated_email.json["retry_after_seconds"] > 0


def test_guest_upload_offers_existing_account_choice(client):
    from app.services.user_service import register_user

    with client.application.app_context():
        register_user("already@example.org", "LongEnoughPassword!123")
    csrf_token = switch_to_guest(client)
    response = client.post(
        "/api/guest/jobs",
        data={"email": "Already@example.org", "file": (io.BytesIO(valid_pdf_bytes()), "account.pdf")},
        headers={"X-CSRF-Token": csrf_token}, content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert response.json["code"] == "ACCOUNT_EXISTS"


def test_verified_account_claims_recent_guest_report(client):
    import json
    from datetime import datetime
    from app.models import AnalysisJob, UploadedDocument, User
    from app.services.email_verification import claim_guest_reports_for_user
    from app.services.user_service import register_user

    with client.application.app_context():
        user = register_user("guest-owner@example.org", "LongEnoughPassword!123")
        completed_at = datetime(2026, 11, 12, 0, 32, 0)
        job = AnalysisJob(
            id="b" * 32, guest_owner="guest-hash", user_id=None,
            email=user.email, filename="guest-paper.pdf", pdf_path="/tmp/no-guest-file.pdf",
            status="completed", report_json=json.dumps({"results": [{
                "title": "Guest reference", "authors": "A Reader", "year": 2024,
                "doi": "10.1234/guest", "is_retracted": False,
                "verification_status": "verified",
            }]}), finished_at=completed_at,
        )
        db.session.add(job)
        db.session.commit()
        assert claim_guest_reports_for_user(user) == 1
        db.session.refresh(job)
        assert job.user_id == user.id
        assert job.guest_owner is None
        assert job.report_json is None
        assert job.document_id is not None
        document = db.session.get(UploadedDocument, job.document_id)
        assert document.upload_date == completed_at
        assert document.last_checked_at == completed_at
        assert claim_guest_reports_for_user(user) == 0
        assert UploadedDocument.query.filter_by(user_id=user.id, filename="guest-paper.pdf").count() == 1


def test_worker_does_not_overwrite_cancellation(client, monkeypatch):
    from app import analysis_worker
    from app.models import AnalysisJob, UploadedDocument

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "cancel-during-run.pdf")},
        content_type="multipart/form-data",
    )
    job_id = queued.json["job_id"]

    def cancel_during_grobid(_path):
        AnalysisJob.query.filter_by(id=job_id).update({"status": "cancelled"})
        db.session.commit()
        return [{"title": "Must not be saved", "doi": "10.1234/cancelled"}]

    monkeypatch.setattr("app.analysis_worker.process_pdf", cancel_during_grobid)
    monkeypatch.setattr("app.analysis_worker.send_ready_email", lambda _job: None)
    assert analysis_worker.process_next_job(client.application)
    with client.application.app_context():
        assert db.session.get(AnalysisJob, job_id).status == "cancelled"
        assert UploadedDocument.query.filter_by(filename="cancel-during-run.pdf").count() == 0


def test_worker_records_grobid_empty_response_code(client, monkeypatch):
    from app import analysis_worker
    from app.models import AnalysisJob
    from app.services.grobid import GrobidServiceError

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "empty-response.pdf")},
        content_type="multipart/form-data",
    )
    assert queued.status_code == 202

    def return_empty_grobid_response(_path):
        raise GrobidServiceError("GROBID returned an empty response.")

    monkeypatch.setattr(
        "app.analysis_worker.process_pdf",
        return_empty_grobid_response,
    )
    assert analysis_worker.process_next_job(client.application)

    with client.application.app_context():
        job = db.session.get(AnalysisJob, queued.json["job_id"])
        assert job.status == "failed"
        assert job.error_code == "GROBID_EMPTY_RESPONSE"


def test_completed_job_stays_saved_when_email_settings_are_missing(client, monkeypatch):
    from app import analysis_worker
    from app.models import AnalysisJob

    queued = client.post(
        "/api/jobs",
        data={"file": (io.BytesIO(valid_pdf_bytes()), "email_notice.pdf")},
        content_type="multipart/form-data",
    )
    assert queued.status_code == 202
    monkeypatch.setattr(
        "app.analysis_worker.process_pdf",
        lambda _path: [{"title": "Example", "doi": "10.1234/example", "retracted": False}],
    )
    for key in ("SMTP_HOST", "MAIL_FROM", "APP_PUBLIC_URL"):
        monkeypatch.delenv(key, raising=False)
    assert analysis_worker.process_next_job(client.application)
    with client.application.app_context():
        job = db.session.get(AnalysisJob, queued.json["job_id"])
        assert job.status == "completed"
        assert job.email_sent is False
        assert "not configured" in job.email_error
    status = client.get("/api/jobs").json
    assert status["email_warnings"] == ["email_notice.pdf"]


def test_guest_ready_email_attaches_a_pdf_report(client, monkeypatch):
    import json
    from app.analysis_worker import send_ready_email
    from app.models import AnalysisJob
    from app.services.analysis_jobs import guest_job_from_token

    captured = []

    monkeypatch.setenv("APP_PUBLIC_URL", "https://checker.example.org")
    monkeypatch.setattr(
        "app.analysis_worker.send_email",
        lambda recipient, subject, body, **kwargs: captured.append((recipient, subject, body, kwargs)),
    )
    job = AnalysisJob(
        id="a" * 32,
        guest_owner="owner-hash",
        email="reader@example.org",
        filename="paper.pdf",
        pdf_path="/tmp/unused-test.pdf",
        status="completed",
        report_json=json.dumps({"document": {"filename": "paper.pdf"}, "total_references": 1,
            "retracted_references": 1, "results": [{"title": "Retracted paper",
                "verification_status": "retracted", "doi": "10.1234/example"}]}),
    )
    with client.application.app_context():
        db.session.add(job)
        db.session.commit()
        send_ready_email(job)
        assert len(captured) == 1
        assert captured[0][0] == "reader@example.org"
        assert "attached as a PDF" in captured[0][2]
        assert "https://checker.example.org/guest/reports/" + job.id in captured[0][2]
        token = captured[0][2].split("?access=", 1)[1].split()[0]
        assert guest_job_from_token(job.id, token).id == job.id
        filename, pdf, maintype, subtype = captured[0][3]["attachments"][0]
        assert filename == "paper-report.pdf"
        assert (maintype, subtype) == ("application", "pdf")
        from pypdf import PdfReader
        import io
        parsed = PdfReader(io.BytesIO(pdf))
        assert "Retracted paper" in parsed.pages[0].extract_text()


def test_guest_analysis_rate_limit_returns_json(client):
    from app.main import limiter

    limiter.reset()
    csrf_token = switch_to_guest(client)
    responses = [
        client.post(
            "/api/guest/analyze",
            headers={"X-CSRF-Token": csrf_token},
        )
        for _ in range(4)
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 429]
    assert responses[-1].json["code"] == "RATE_LIMITED"


def test_retracted_only_filter_returns_only_retracted_references(client):
    upload_response = client.post(
        "/api/analyze",
        data={
            "file": (
                io.BytesIO(valid_pdf_bytes()),
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
    assert response.json["code"] == "FILE_TOO_LARGE"
    assert response.json["message"] == (
        "The uploaded file exceeds the maximum allowed size of 16 MB."
    )


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
                io.BytesIO(valid_pdf_bytes()),
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

    from app.models import User
    with client.application.app_context():
        second_user = User.query.filter_by(email="second_user@example.com").one()
        second_user.email_verified = True
        db.session.commit()

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

    monkeypatch.setattr(
        run_grobid_pipeline,
        "verify_references_doi_identity",
        lambda references: [
            {**reference, "doi_identity_verified": True, "verification_note": None}
            for reference in references
        ],
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
                io.BytesIO(valid_pdf_bytes()),
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


def test_new_account_must_confirm_email_before_login(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.route_modules.auth.send_verification_email",
        lambda recipient, token: sent.append((recipient, token)),
    )
    registration = client.post(
        "/api/register",
        json={
            "email": "confirm_me@example.org",
            "password": "StrongTestPassword123!",
        },
    )
    assert registration.status_code == 201
    assert registration.json["status"] == "pending_verification"
    assert sent[0][0] == "confirm_me@example.org"

    login_before_confirmation = client.post(
        "/api/login",
        json={
            "email": "confirm_me@example.org",
            "password": "StrongTestPassword123!",
        },
    )
    assert login_before_confirmation.status_code == 403
    assert login_before_confirmation.json["code"] == "EMAIL_NOT_VERIFIED"

    confirmed = client.post("/api/verify-email", json={"token": sent[0][1]})
    assert confirmed.status_code == 200
    assert confirmed.json["status"] == "success"
    assert client.post(
        "/api/verify-email", json={"token": sent[0][1]},
    ).status_code == 400

    login_after_confirmation = client.post(
        "/api/login",
        json={
            "email": "confirm_me@example.org",
            "password": "StrongTestPassword123!",
        },
    )
    assert login_after_confirmation.status_code == 200


def test_resending_confirmation_invalidates_the_previous_link(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.route_modules.auth.send_verification_email",
        lambda recipient, token: sent.append((recipient, token)),
    )
    client.post(
        "/api/register",
        json={
            "email": "resend_me@example.org",
            "password": "StrongTestPassword123!",
        },
    )
    response = client.post(
        "/api/resend-verification",
        json={"email": "resend_me@example.org"},
    )
    assert response.status_code == 200
    assert len(sent) == 2
    assert client.post(
        "/api/verify-email", json={"token": sent[0][1]},
    ).status_code == 400
    assert client.post(
        "/api/verify-email", json={"token": sent[1][1]},
    ).status_code == 200


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
    assert response.json["code"] == "INVALID_FILE_FORMAT"


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
    assert response.json["code"] == "INVALID_FILE_FORMAT"


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
