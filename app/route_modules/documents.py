
from pathlib import Path
from uuid import uuid4

from flask import jsonify, request
from sqlalchemy.orm import selectinload

from app.database import db
from app.models import (
    UploadedDocument,
    ExtractedReference,
    DetectionResult,
)
from app.run_grobid_pipeline import process_pdf
from app.services.database_service import save_analysis_results
from app.route_modules.helpers import (
    current_user_id,
    login_required,
)


def owned_document(document_id, user_id):
    """Return an owned document with all required related data."""

    return (
        UploadedDocument.query
        .options(
            selectinload(UploadedDocument.references)
            .selectinload(ExtractedReference.detection_results)
            .selectinload(DetectionResult.retracted_publication)
        )
        .filter_by(
            id=document_id,
            user_id=user_id,
        )
        .first()
    )


def register_document_routes(app):
    """Register document analysis and history routes."""

    if app.config.get("APP_ENV") != "production":

        @app.route("/api/test-analysis", methods=["POST"])
        @login_required
        def test_analysis():
            pdf_path = (
                Path(app.root_path).parent
                / "tests"
                / "fixtures"
                / "testychat.pdf"
            )

            if not pdf_path.is_file():
                return jsonify({
                    "status": "error",
                    "message": "Test PDF was not found.",
                }), 404

            try:
                references = process_pdf(str(pdf_path))

                document_id = save_analysis_results(
                    user_id=current_user_id(),
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
    @login_required
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
                "message": (
                    "The uploaded file does not appear to be a valid PDF."
                ),
            }), 400

        upload_dir = Path(app.root_path).parent / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = upload_dir / f"{uuid4().hex}.pdf"

        try:
            uploaded_file.save(pdf_path)

            references = process_pdf(str(pdf_path))
            filename = Path(uploaded_file.filename).name

            document_id = save_analysis_results(
                user_id=current_user_id(),
                filename=filename,
                references=references,
            )

            return jsonify({
                "status": "success",
                "document_id": document_id,
                "filename": filename,
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
                try:
                    pdf_path.unlink()
                except OSError:
                    app.logger.exception(
                        "Could not delete temporary PDF"
                    )

    @app.route(
        "/api/documents/<int:document_id>/results",
        methods=["GET"],
    )
    @login_required
    def get_document_results(document_id):
        document = owned_document(
            document_id,
            current_user_id(),
        )

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
                reference.detection_results[0]
                if reference.detection_results
                else None
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
    @login_required
    def list_documents():
        documents = (
            UploadedDocument.query
            .options(
                selectinload(UploadedDocument.references)
                .selectinload(ExtractedReference.detection_results)
            )
            .filter_by(user_id=current_user_id())
            .order_by(UploadedDocument.upload_date.desc())
            .all()
        )

        document_list = []

        for document in documents:
            retracted_count = sum(
                1
                for reference in document.references
                if any(
                    detection.is_retracted
                    for detection in reference.detection_results
                )
            )

            document_list.append({
                "id": document.id,
                "filename": document.filename,
                "upload_date": document.upload_date.isoformat(),
                "processing_status": document.processing_status,
                "total_references": len(document.references),
                "retracted_references": retracted_count,
            })

        return jsonify({
            "status": "success",
            "total_documents": len(document_list),
            "documents": document_list,
        }), 200
