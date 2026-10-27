
from main import app
from models import UploadedDocument, ExtractedReference, DetectionResult

with app.app_context():
    print("Database URI:", app.config["SQLALCHEMY_DATABASE_URI"])

    documents = UploadedDocument.query.order_by(
        UploadedDocument.id
    ).all()

    print("Documents found:", len(documents))

    for document in documents:
        print("\nDocument ID:", document.id)
        print("Filename:", document.filename)
        print("Status:", document.processing_status)
        print("References saved:", len(document.references))

        results = (
            DetectionResult.query
            .join(ExtractedReference)
            .filter(ExtractedReference.document_id == document.id)
            .all()
        )

        print("Detection results:", len(results))
        print(
            "Retracted references:",
            sum(1 for result in results if result.is_retracted)
        )
