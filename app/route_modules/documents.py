
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import time
from uuid import uuid4

from flask import current_app, jsonify, request, session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.database import db
from app.models import (
    AnalysisJob,
    User,
    UploadedDocument,
    ExtractedReference,
    DetectionResult,
    DocumentWatch,
    Notification,
    RetractedPublication,
)
from app.main import limiter
from app.run_grobid_pipeline import CSV_PATH, process_pdf
from app.services.database_service import save_analysis_results
from app.services.doi import normalize_doi
from app.services.grobid import GrobidServiceError
from app.services.guest_reports import GuestReportStore, current_guest_owner
from app.services.analysis_jobs import (
    enqueue_pdf,
    guest_job_for_owner,
    guest_job_from_token,
    job_payload,
)
from app.services.pdf_validation import PdfValidationError, validate_pdf
from app.services.retractions import (
    RetractionDataError,
    RetractionService,
    ensure_retractions_dataset,
)
from app.route_modules.helpers import (
    current_user_id,
    login_required,
)


TEMPORARY_PDF_PATTERN = re.compile(r"^[0-9a-f]{32}\.pdf$")
guest_reports = GuestReportStore(ttl_seconds=60 * 60, max_reports=256, start_expirer=True)


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


def error_response(code, message, status_code):
    return jsonify({
        "status": "error",
        "code": code,
        "message": message,
    }), status_code


def cleanup_stale_uploads(upload_dir: Path, max_age_seconds=24 * 60 * 60):
    """Remove only app-named temporary PDFs left by an interrupted request."""

    if not upload_dir.is_dir():
        return 0

    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in upload_dir.iterdir():
        if not path.is_file() or not TEMPORARY_PDF_PATTERN.fullmatch(path.name):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            current_app.logger.exception(
                "Could not remove an expired temporary PDF."
            )
    return removed


@contextmanager
def temporary_uploaded_pdf(app, uploaded_file):
    """Validate, temporarily save, and always remove an uploaded PDF."""

    if not uploaded_file.filename:
        raise PdfValidationError(
            "FILE_MISSING",
            "Please choose a PDF file to upload.",
            400,
        )

    if Path(uploaded_file.filename).suffix.lower() != ".pdf":
        raise PdfValidationError(
            "INVALID_FILE_FORMAT",
            "Invalid file format. Please upload a valid PDF file.",
            400,
        )

    uploaded_file.stream.seek(0, 2)
    file_size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if file_size > app.config["MAX_UPLOAD_SIZE_BYTES"]:
        raise PdfValidationError(
            "FILE_TOO_LARGE",
            "The uploaded file exceeds the maximum allowed size of 16 MB.",
            413,
        )

    file_header = uploaded_file.stream.read(5)
    uploaded_file.stream.seek(0)
    if file_header != b"%PDF-":
        raise PdfValidationError(
            "INVALID_FILE_FORMAT",
            "Invalid file format. Please upload a valid PDF file.",
            400,
        )

    validate_pdf(uploaded_file.stream)
    uploaded_file.stream.seek(0)

    upload_dir = Path(app.root_path).parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_uploads(upload_dir)
    pdf_path = upload_dir / f"{uuid4().hex}.pdf"

    try:
        uploaded_file.save(pdf_path)
        yield pdf_path
    finally:
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except OSError:
                app.logger.exception("Could not remove temporary uploaded PDF.")


def analysis_failure_response(app, error):
    """Log a processing exception and return a safe, typed API response."""

    db.session.rollback()
    if isinstance(error, PdfValidationError):
        return error_response(error.code, error.message, error.status_code)
    if isinstance(error, GrobidServiceError):
        code = "REFERENCE_EXTRACTION_UNAVAILABLE"
        message = "Reference extraction is temporarily unavailable. Please try again later."
        status_code = 503
        log_message = "Reference extraction failed during PDF analysis."
    elif isinstance(error, RetractionDataError):
        code = "RETRACTION_DATA_UNAVAILABLE"
        message = "Retraction data is temporarily unavailable. Please try again later."
        status_code = 503
        log_message = "Retraction data unavailable during PDF analysis."
    elif isinstance(error, SQLAlchemyError):
        code = "DATABASE_SAVE_FAILED"
        message = "The document could not be processed. Please try again."
        status_code = 500
        log_message = "Database save failed during PDF analysis."
    else:
        code = "ANALYSIS_FAILED"
        message = "The document could not be processed. Please try again."
        status_code = 500
        log_message = "Unexpected PDF analysis failure."

    app.logger.exception(log_message)
    return error_response(code, message, status_code)


def drain_queued_analysis(app):
    """Process the oldest queued job before a direct analysis request."""
    try:
        from app.analysis_worker import process_next_job

        with app.app_context():
            return process_next_job(app)
    except Exception:
        app.logger.exception("Queued analysis drain failed.")
        return False


def guest_report_payload(filename, references):
    results = []
    for reference_id, reference in enumerate(references, start=1):
        doi = reference.get("doi")
        is_retracted = reference.get("retracted") is True
        verification_status = reference.get("verification_status")
        if verification_status not in {
            "retracted",
            "verified",
            "not_verified",
            "missing_doi",
        }:
            if is_retracted:
                verification_status = "retracted"
            elif not doi:
                verification_status = "missing_doi"
            else:
                verification_status = "not_verified"

        authors = reference.get("authors")
        if isinstance(authors, list):
            authors = ", ".join(authors)

        results.append({
            "reference_id": reference_id,
            "title": reference.get("title"),
            "authors": authors,
            "year": reference.get("year"),
            "doi": doi,
            "pmid": reference.get("pmid"),
            "is_retracted": is_retracted,
            "verification_status": verification_status,
            "verification_note": reference.get("verification_note"),
            "detection_method": reference.get("detection_method"),
            "retracted_publication": (
                {
                    "title": reference.get("title"),
                    "doi": doi,
                    "source": "Retraction Watch",
                    "retraction_reason": reference.get("retraction_reason"),
                }
                if is_retracted
                else None
            ),
        })

    return {
        "status": "success",
        "document": {
            "id": None,
            "filename": filename,
            "upload_date": datetime.now(timezone.utc).isoformat(),
            "processing_status": "completed",
        },
        "total_references": len(results),
        "retracted_references": sum(
            1 for result in results if result["is_retracted"]
        ),
        "results": results,
    }


def register_document_routes(app):
    """Register document analysis and history routes."""

    cleanup_stale_uploads(Path(app.root_path).parent / "uploads")

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

            except Exception as exc:
                app.logger.exception("Test PDF analysis failed")
                return analysis_failure_response(app, exc)

    @app.route("/api/analyze", methods=["POST"])
    @login_required
    def analyze_pdf():
        if "file" not in request.files:
            return error_response(
                "FILE_MISSING",
                "Please choose a PDF file to upload.",
                400,
            )

        # If the app is running without a dedicated worker, drain the oldest queued
        # job before processing the newly uploaded PDF.
        drain_queued_analysis(app)

        uploaded_file = request.files["file"]
        try:
            with temporary_uploaded_pdf(app, uploaded_file) as pdf_path:
                references = process_pdf(str(pdf_path))
            if not references:
                return error_response("NO_REFERENCES_FOUND", "No references were found in this document.", 422)
            filename = Path(uploaded_file.filename).name
            document_id = save_analysis_results(
                user_id=current_user_id(), filename=filename, references=references,
            )
            return jsonify({
                "status": "success", "document_id": document_id,
                "filename": filename, "references_processed": len(references),
                "retracted_references": sum(1 for ref in references if ref.get("retracted")),
            }), 200
        except Exception as exc:
            return analysis_failure_response(app, exc)

    @app.route("/api/jobs", methods=["POST"])
    @login_required
    def enqueue_analysis():
        if "file" not in request.files:
            return error_response("FILE_MISSING", "Please choose a PDF file to upload.", 400)
        try:
            user = User.query.filter_by(id=current_user_id()).first()
            if user is None:
                return error_response("AUTHENTICATION_REQUIRED", "Please sign in again.", 401)
            job = enqueue_pdf(
                request.files["file"],
                user_id=user.id,
                email=user.email,
            )
            return jsonify({
                "status": "queued",
                "job_id": job.id,
                "filename": job.filename,
            }), 202

        except Exception as exc:
            return analysis_failure_response(app, exc)

    @app.route("/api/jobs", methods=["GET"])
    @login_required
    def get_analysis_jobs():
        jobs = (
            AnalysisJob.query.filter(
                AnalysisJob.user_id == current_user_id(),
                AnalysisJob.status.in_(["queued", "running"]),
            )
            .order_by(AnalysisJob.created_at.desc())
            .all()
        )
        email_warnings = (
            AnalysisJob.query.filter(
                AnalysisJob.user_id == current_user_id(),
                AnalysisJob.status == "completed",
                AnalysisJob.email_sent.is_(False),
                AnalysisJob.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48),
            )
            .order_by(AnalysisJob.created_at.desc())
            .limit(5)
            .all()
        )
        return jsonify({
            "jobs": [job_payload(job) for job in jobs],
            "email_warnings": [job.filename for job in email_warnings],
        }), 200

    @app.route("/api/jobs/<job_id>", methods=["DELETE"])
    @login_required
    def cancel_analysis_job(job_id):
        job = AnalysisJob.query.filter_by(
            id=job_id,
            user_id=current_user_id(),
        ).first()
        if job is None:
            return error_response(
                "JOB_NOT_FOUND",
                "The queued file could not be found.",
                404,
            )

        if job.status in {"queued", "running"}:
            if job.status == "queued":
                path = Path(job.pdf_path)
                if path.exists():
                    path.unlink(missing_ok=True)
                db.session.delete(job)
            else:
                job.status = "cancelled"
                job.error_code = "CANCELLED"
                job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                path = Path(job.pdf_path)
                if path.exists():
                    path.unlink(missing_ok=True)
            db.session.commit()
            return jsonify({
                "status": "cancelled",
                "job_id": job_id,
                "filename": job.filename,
            }), 200

        return jsonify({
            "status": "success",
            "job_id": job_id,
            "filename": job.filename,
            "message": "This job is no longer active.",
        }), 200

    # Keep the original synchronous guest endpoint for API compatibility.
    @app.route("/api/guest/analyze", methods=["POST"])
    @limiter.limit("3 per hour")
    def analyze_as_guest_legacy():
        if "file" not in request.files:
            return error_response("FILE_MISSING", "Please choose a PDF file to upload.", 400)
        owner_key = current_guest_owner(session)
        if guest_reports.has_owner(owner_key):
            return error_response(
                "GUEST_SESSION_LIMIT",
                "Your guest analysis is ready. Create an account to analyze more documents.",
                429,
            )
        uploaded_file = request.files["file"]
        try:
            with temporary_uploaded_pdf(app, uploaded_file) as pdf_path:
                references = process_pdf(str(pdf_path))
            if not references:
                return error_response("NO_REFERENCES_FOUND", "No references were found in this document.", 422)
            filename = Path(uploaded_file.filename).name
            payload = guest_report_payload(filename, references)
            payload["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=guest_reports.ttl_seconds)
            ).isoformat()
            report_id, reason = guest_reports.create(owner_key, payload)
            if reason == "capacity":
                return error_response("GUEST_CAPACITY_FULL", "Guest analysis is temporarily unavailable. Please try again later.", 503)
            return jsonify({
                "status": "success", "report_id": report_id,
                "filename": filename, "references_processed": len(references),
                "retracted_references": payload["retracted_references"],
                "expires_at": payload["expires_at"],
            }), 200
        except Exception as exc:
            return analysis_failure_response(app, exc)

    @app.route("/api/guest/jobs", methods=["POST"])
    @limiter.limit("3 per hour")
    def analyze_as_guest():
        if "file" not in request.files:
            return error_response(
                "FILE_MISSING",
                "Please choose a PDF file to upload.",
                400,
            )

        owner_key = current_guest_owner(session)
        active_guest_job = AnalysisJob.query.filter(
            AnalysisJob.guest_owner == owner_key,
            AnalysisJob.status.in_(["queued", "running", "completed"]),
            AnalysisJob.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48),
        ).first()
        if active_guest_job:
            if active_guest_job.status == "completed":
                return error_response(
                    "GUEST_SESSION_LIMIT",
                    "Your guest report is ready. Create an account to run another analysis.",
                    429,
                )
            return error_response(
                "GUEST_ANALYSIS_IN_PROGRESS",
                "Your guest analysis is still running. Keep its report link to check the result later.",
                429,
            )
        try:
            email = (request.form.get("email") or "").strip().lower()
            if len(email) > 255 or "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                return error_response("EMAIL_REQUIRED", "Enter a valid email address so we can send the report link.", 400)
            job = enqueue_pdf(
                request.files["file"],
                guest_owner=owner_key,
                email=email,
            )
            return jsonify({
                "status": "queued",
                "report_id": job.id,
                "filename": job.filename,
            }), 202
        except Exception as exc:
            return analysis_failure_response(app, exc)

    @app.route("/api/guest/reports/<string:report_id>", methods=["GET"])
    def get_guest_report(report_id):
        owner_key = current_guest_owner(session)
        legacy_report = guest_reports.get(report_id, owner_key)
        if legacy_report is not None:
            return jsonify(legacy_report), 200
        job = guest_job_for_owner(report_id, owner_key)
        if job is None:
            job = guest_job_from_token(report_id, request.args.get("access"))
        if job is None:
            return error_response(
                "GUEST_REPORT_NOT_FOUND",
                "This report link has expired or is unavailable.",
                404,
            )
        if job.finished_at and job.finished_at < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48):
            return error_response(
                "GUEST_REPORT_EXPIRED",
                "This temporary report has expired.",
                404,
            )
        result = job_payload(job)
        result["expires_at"] = (
            (job.finished_at + timedelta(hours=48)).isoformat() + "Z"
            if job.finished_at else None
        )
        return jsonify(result), 200

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
                "verification_status": (
                    detection.verification_status
                    if detection is not None
                    else "not_verified"
                ),
                "verification_note": (
                    detection.verification_note
                    if detection is not None
                    else None
                ),
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

    @app.route("/api/documents/watchlist", methods=["GET"])
    @login_required
    def get_document_watchlist():
        watched = (
            DocumentWatch.query
            .filter_by(user_id=current_user_id(), is_active=True)
            .order_by(DocumentWatch.created_at.desc())
            .all()
        )
        return jsonify({
            "status": "success",
            "watchlist": [entry.document_id for entry in watched],
        }), 200

    @app.route("/api/documents/<int:document_id>/watch", methods=["POST"])
    @login_required
    def add_document_to_watchlist(document_id):
        document = UploadedDocument.query.filter_by(
            id=document_id,
            user_id=current_user_id(),
        ).first()
        if document is None:
            return error_response(
                "DOCUMENT_NOT_FOUND",
                "Document not found.",
                404,
            )

        watch_entry = DocumentWatch.query.filter_by(
            user_id=current_user_id(),
            document_id=document_id,
        ).first()
        if watch_entry is None:
            watch_entry = DocumentWatch(
                user_id=current_user_id(),
                document_id=document_id,
            )
            db.session.add(watch_entry)
        watch_entry.is_active = True
        watch_entry.last_checked_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            "status": "success",
            "document_id": document_id,
            "watched": True,
        }), 200

    @app.route("/api/documents/<int:document_id>/watch", methods=["DELETE"])
    @login_required
    def remove_document_from_watchlist(document_id):
        watch_entry = DocumentWatch.query.filter_by(
            user_id=current_user_id(),
            document_id=document_id,
        ).first()
        if watch_entry is None:
            return jsonify({
                "status": "success",
                "document_id": document_id,
                "watched": False,
            }), 200

        db.session.delete(watch_entry)
        db.session.commit()

        return jsonify({
            "status": "success",
            "document_id": document_id,
            "watched": False,
        }), 200

    @app.route(
        "/api/documents/<int:document_id>/refresh",
        methods=["POST"],
    )
    @login_required
    def refresh_document_retractions(document_id):
        document = owned_document(document_id, current_user_id())
        if document is None:
            return error_response(
                "DOCUMENT_NOT_FOUND",
                "Document not found.",
                404,
            )

        try:
            ensure_retractions_dataset(CSV_PATH)
            service = RetractionService(CSV_PATH)
            refreshed = 0

            for reference in document.references:
                if not reference.detection_results:
                    continue

                detection = reference.detection_results[0]
                doi = normalize_doi(reference.doi)

                if not doi:
                    detection.is_retracted = False
                    detection.verification_status = "missing_doi"
                    detection.verification_note = None
                    detection.retracted_publication_id = None
                    refreshed += 1
                    continue

                if service.is_retracted(doi):
                    publication = RetractedPublication.query.filter_by(doi=doi).first()
                    if publication is None:
                        publication = RetractedPublication(
                            doi=doi,
                            pmid=reference.pmid,
                            title=reference.title,
                            retraction_reason=service.get_retraction_reason(doi),
                            source="Retraction Watch",
                        )
                        db.session.add(publication)
                        db.session.flush()

                    detection.is_retracted = True
                    detection.verification_status = "retracted"
                    detection.verification_note = "This reference is now listed as retracted in Retraction Watch."
                    detection.retracted_publication_id = publication.id
                    refreshed += 1
                    continue

                detection.is_retracted = False
                detection.verification_status = "verified"
                detection.verification_note = None
                detection.retracted_publication_id = None
                refreshed += 1

            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return analysis_failure_response(app, exc)

        return jsonify({
            "status": "success",
            "document_id": document.id,
            "message": "Document checks refreshed.",
            "refreshed": refreshed,
        }), 200

    @app.route(
        "/api/documents/<int:document_id>",
        methods=["DELETE"],
    )
    @login_required
    def delete_document(document_id):
        document = UploadedDocument.query.filter_by(
            id=document_id,
            user_id=current_user_id(),
        ).first()

        if document is None:
            return error_response(
                "DOCUMENT_NOT_FOUND",
                "Document not found.",
                404,
            )

        try:
            # Keep notifications while removing their link to this analysis.
            db.session.query(Notification).filter_by(
                document_id=document.id,
            ).update(
                {Notification.document_id: None},
                synchronize_session=False,
            )
            db.session.delete(document)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Could not delete analysis history record.")
            return error_response(
                "DOCUMENT_DELETE_FAILED",
                "The analysis could not be deleted. Please try again.",
                500,
            )

        return jsonify({
            "status": "success",
            "message": "Analysis deleted.",
            "document_id": document_id,
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
        watched_document_ids = {
            entry.document_id
            for entry in DocumentWatch.query.filter_by(
                user_id=current_user_id(),
                is_active=True,
            ).all()
        }

        for document in sorted(
            documents,
            key=lambda item: item.upload_date,
            reverse=True,
        ):
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
                "is_watched": document.id in watched_document_ids,
            })

        return jsonify({
            "status": "success",
            "total_documents": len(document_list),
            "documents": document_list,
        }), 200
