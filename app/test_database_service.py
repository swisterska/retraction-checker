
from app.database import db
from app.main import create_app
from app.models import UploadedDocument, User
from app.services.database_service import save_analysis_results


def test_save_analysis_results():
    test_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
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
