
from pathlib import Path
from uuid import uuid4

from flask import jsonify, request

from app.database import db
from app.models import (
    User,
    UploadedDocument,
    ExtractedReference,
    DetectionResult,
)
from app.run_grobid_pipeline import process_pdf
from app.services.database_service import save_analysis_results


def register_routes(app):

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify({
            "status": "error",
            "message": "File is too large. Maximum request size is 16 MB.",
        }), 413

    @app.route("/")
    def index():
        return "<h1>System Retraction Checker is working</h1>"

    @app.route("/api/test-analysis", methods=["POST"])
    def test_analysis():
        pdf_path = "uploads/testychat.pdf"

        try:
            references = process_pdf(pdf_path)

            test_email = "pipeline_test@example.com"
            user = User.query.filter_by(email=test_email).first()

            if user is None:
                user = User(
                    email=test_email,
                    password_hash="development-test-account",
                )
                db.session.add(user)
                db.session.commit()

            document_id = save_analysis_results(
                user_id=user.id,
                filename="testychat.pdf",
                references=references,
            )

            return jsonify({
                "status": "success",
                "document_id": document_id,
                "references_processed": len(references),
                "retracted_references": sum(
                    1 for ref in references if ref.get("retracted")
                ),
            }), 200

        except Exception:
            db.session.rollback()
            app.logger.exception("Test PDF analysis failed")
            return jsonify({
                "status": "error",
                "message": (
                    "PDF analysis or database saving failed. "
                    "Check the application logs."
                ),
            }), 500

    @app.route("/api/analyze", methods=["POST"])

    def analyze_pdf():
        if "file" not in request.files:
            return jsonify({
                "status": "error",
                "message": "No file provided. Use the 'file' field.",
            }), 400

        uploaded_file = request.files["file"]

        if not uploaded_file.filename:
            return jsonify({
                "status": "error",
                "message": "No file selected.",
            }), 400

        if Path(uploaded_file.filename).suffix.lower() != ".pdf":
            return jsonify({
                "status": "error",
                "message": "Only PDF files are allowed.",
            }), 400

        file_header = uploaded_file.stream.read(5)
        uploaded_file.stream.seek(0)

        if file_header != b"%PDF-":
            return jsonify({
                "status": "error",
                "message": "The uploaded file does not appear to be a valid PDF.",
            }), 400

        upload_dir = Path(app.root_path).parent / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = f"{uuid4().hex}.pdf"
        pdf_path = upload_dir / safe_filename

        try:
            uploaded_file.save(pdf_path)

            references = process_pdf(str(pdf_path))

            test_email = "pipeline_test@example.com"
            user = User.query.filter_by(email=test_email).first()

            if user is None:
                user = User(
                    email=test_email,
                    password_hash="development-test-account",
                )
                db.session.add(user)
                db.session.commit()

            document_id = save_analysis_results(
                user_id=user.id,
                filename=uploaded_file.filename,
                references=references,
            )

            return jsonify({
                "status": "success",
                "document_id": document_id,
                "filename": uploaded_file.filename,
                "references_processed": len(references),
                "retracted_references": sum(
                    1 for ref in references if ref.get("retracted")
                ),
            }), 200

        except Exception:
            db.session.rollback()
            app.logger.exception("PDF analysis failed")
            return jsonify({
                "status": "error",
                "message": (
                    "PDF analysis or database saving failed. "
                    "Check the application logs."
                ),
            }), 500

        finally:
            if pdf_path.exists():
                pdf_path.unlink()

    
    
    @app.route("/api/documents/<int:document_id>/results", methods=["GET"])
    def get_document_results(document_id):
        document = db.session.get(UploadedDocument, document_id)

        if document is None:
            return jsonify({
                "status": "error",
                "message": "Document not found.",
            }), 404

        retracted_only = (
            request.args.get("retracted_only", "false").lower() == "true"
        )

        results = []

        for reference in document.references:
            detection = (
                DetectionResult.query
                .filter_by(reference_id=reference.id)
                .first()
            )

            is_retracted = (
                detection.is_retracted
                if detection is not None
                else None
            )

            if retracted_only and is_retracted is not True:
                continue

            publication = (
                detection.retracted_publication
                if detection is not None
                else None
            )

            results.append({
                "reference_id": reference.id,
                "title": reference.title,
                "authors": reference.authors,
                "year": reference.year,
                "doi": reference.doi,
                "pmid": reference.pmid,
                "is_retracted": is_retracted,
                "detection_method": (
                    detection.detection_method
                    if detection is not None
                    else None
                ),
                "retracted_publication": (
                    {
                        "title": publication.title,
                        "doi": publication.doi,
                        "source": publication.source,
                        "retraction_reason": publication.retraction_reason,
                    }
                    if publication is not None
                    else None
                ),
            })

        return jsonify({
            "status": "success",
            "document": {
                "id": document.id,
                "filename": document.filename,
                "upload_date": document.upload_date.isoformat(),
                "processing_status": document.processing_status,
            },
            "total_references": len(results),
            "retracted_references": sum(
                1 for result in results
                if result["is_retracted"] is True
            ),
            "results": results,
        }), 200


    
    @app.route("/api/documents", methods=["GET"])
    def list_documents():
        documents = (
            UploadedDocument.query
            .order_by(UploadedDocument.upload_date.desc())
            .all()
        )

        document_list = []

        for document in documents:
            references = document.references

            retracted_count = 0

            for reference in references:
                for detection in reference.detection_results:
                    if detection.is_retracted:
                        retracted_count += 1
                        break

            document_list.append({
                "id": document.id,
                "filename": document.filename,
                "upload_date": document.upload_date.isoformat(),
                "processing_status": document.processing_status,
                "total_references": len(references),
                "retracted_references": retracted_count,
            })

        return jsonify({
            "status": "success",
            "total_documents": len(document_list),
            "documents": document_list,
        }), 200
        
