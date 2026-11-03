
from app.database import db
from app.main import create_app
from app.models import UploadedDocument, User
from app.services.database_service import save_analysis_results
import pytest


def test_save_analysis_results():
    test_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {
            "users": "sqlite://",
        },
    })

    with test_app.app_context():
        db.create_all()

        try:
            user = User(
                email="database_service_test@example.com",
                password_hash="test_hash_not_for_real_login",
            )
            db.session.add(user)
            db.session.flush()

            references = [
                {
                    "title": "Known retracted test publication",
                    "authors": ["Test Author"],
                    "doi": "10.1002/jcb.23190",
                    "pmid": None,
                    "retracted": True,
                    "retraction_reason": "Investigation by Third Party;Removed;",
                },
                {
                    "title": "Example non-retracted publication",
                    "authors": ["Another Author"],
                    "doi": "10.1234/example",
                    "pmid": None,
                    "retracted": False,
                    "retraction_reason": None,
                },
            ]

            document_id = save_analysis_results(
                user_id=user.id,
                filename="database_service_test.pdf",
                references=references,
            )

            document = db.session.get(UploadedDocument, document_id)

            assert document is not None
            assert len(document.references) == 2

            results = [
                result
                for reference in document.references
                for result in reference.detection_results
            ]

            assert len(results) == 2
            assert sum(result.is_retracted for result in results) == 1

            retracted_result = next(
                result for result in results if result.is_retracted
            )
            assert retracted_result.retracted_publication is not None
            assert (
                retracted_result.retracted_publication.retraction_reason
                == "Investigation by Third Party;Removed;"
            )

        finally:
            db.session.rollback()
            db.session.remove()
            db.drop_all()




def test_save_analysis_results_rolls_back_on_error(monkeypatch):
    from app.models import (
        ExtractedReference,
        DetectionResult,
        RetractedPublication,
    )
    from app.services import database_service

    test_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "SQLALCHEMY_BINDS": {
            "users": "sqlite://",
        },
    })

    with test_app.app_context():
        db.create_all()

        try:
            user = User(
                email="rollback_test@example.com",
                password_hash="test_hash_not_for_real_login",
            )
            db.session.add(user)
            db.session.flush()

            original_flush = db.session.flush
            flush_calls = 0

            def failing_flush(*args, **kwargs):
                nonlocal flush_calls
                flush_calls += 1

                if flush_calls == 3:
                    raise RuntimeError("Simulated database failure")

                return original_flush(*args, **kwargs)

            monkeypatch.setattr(
                database_service.db.session,
                "flush",
                failing_flush,
            )

            references = [
                {
                    "title": "Test retracted publication",
                    "doi": "10.1000/test123",
                    "retracted": True,
                    "retraction_reason": "Test reason",
                }
            ]

            with pytest.raises(
                RuntimeError,
                match="Simulated database failure",
            ):
                save_analysis_results(
                    user_id=user.id,
                    filename="rollback_test.pdf",
                    references=references,
                )

            monkeypatch.undo()

            assert UploadedDocument.query.count() == 0
            assert ExtractedReference.query.count() == 0
            assert DetectionResult.query.count() == 0
            assert RetractedPublication.query.count() == 0

        finally:
            db.session.rollback()
            db.session.remove()
            db.drop_all()
