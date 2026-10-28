
import pytest

from app.main import create_app
from app.database import db
from app.models import User, UploadedDocument, ExtractedReference


@pytest.fixture
def app():
    test_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
    })

    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


def test_database_relationships(app):
    with app.app_context():
        user = User(
            email="database_test@example.com",
            password_hash="test_hash_not_for_real_login",
        )
        db.session.add(user)
        db.session.flush()

        document = UploadedDocument(
            user_id=user.id,
            filename="test_document.pdf",
            processing_status="completed",
        )
        db.session.add(document)
        db.session.flush()

        reference = ExtractedReference(
            document_id=document.id,
            title="Example scientific publication",
            doi="10.1234/example",
            raw_reference="Example scientific publication, 2024",
        )
        db.session.add(reference)
        db.session.commit()

        saved_user = db.session.get(User, user.id)
        saved_document = db.session.get(UploadedDocument, document.id)
        saved_reference = db.session.get(ExtractedReference, reference.id)

        assert saved_user is not None
        assert saved_document.user_id == saved_user.id
        assert saved_reference.document_id == saved_document.id
        assert saved_document.user.email == "database_test@example.com"
