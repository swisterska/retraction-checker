
from main import app
from database import db
from models import (
    User,
    UploadedDocument,
    ExtractedReference,
    DetectionResult,
)
from services.database_service import save_analysis_results


def test_save_analysis_results():
    with app.app_context():
        email = "database_service_test@example.com"

        # Create a temporary test user
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(
                email=email,
                password_hash="test_hash_not_for_real_login",
            )
            db.session.add(user)
            db.session.commit()

        # Simulated output from the existing pipeline
        references = [
            {
                "title": "Known retracted test publication",
                "authors": ["Test Author"],
                "doi": "10.1002/jcb.23190",
                "pmid": None,
                "retracted": True,
            },
            {
                "title": "Example non-retracted publication",
                "authors": ["Another Author"],
                "doi": "10.1234/example",
                "pmid": None,
                "retracted": False,
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

        print("Database service test passed!")
        print("Document ID:", document_id)
        print("References saved:", len(document.references))
        print("Detection results:", len(results))
        print("Retracted references:", sum(r.is_retracted for r in results))

        # Clean up the test document and its dependent records
        db.session.delete(document)
        db.session.commit()

        print("Test document and dependent records removed.")


if __name__ == "__main__":
    test_save_analysis_results()
