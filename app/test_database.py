

from main import app
from database import db
from models import User, UploadedDocument, ExtractedReference


def test_database_relationships():
    with app.app_context():
        # Create a test user
        user = User(
            email="database_test@example.com",
            password_hash="test_hash_not_for_real_login",
        )
        db.session.add(user)
        db.session.flush()

        # Create a document belonging to this user
        document = UploadedDocument(
            user_id=user.id,
            filename="test_document.pdf",
            processing_status="completed",
        )
        db.session.add(document)
        db.session.flush()

        # Create a reference extracted from the document
        reference = ExtractedReference(
            document_id=document.id,
            title="Example scientific publication",
            doi="10.1234/example",
            raw_reference="Example scientific publication, 2024",
        )
        db.session.add(reference)
        db.session.commit()

        # Read the records back
        saved_user = db.session.get(User, user.id)
        saved_document = db.session.get(UploadedDocument, document.id)
        saved_reference = db.session.get(ExtractedReference, reference.id)

        assert saved_user is not None
        assert saved_document.user_id == saved_user.id
        assert saved_reference.document_id == saved_document.id
        assert saved_document.user.email == "database_test@example.com"

        print("Database test passed!")
        print(f"User ID: {saved_user.id}")
        print(f"Document ID: {saved_document.id}")
        print(f"Reference ID: {saved_reference.id}")

        # Remove test data
        db.session.delete(saved_user)
        db.session.commit()
        print("Test records removed.")


if __name__ == "__main__":
    test_database_relationships()
