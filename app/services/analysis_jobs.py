"""Queue and access helpers for background PDF analyses."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import hmac
import json
import os

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.database import db
from app.models import AnalysisJob
from app.services.pdf_validation import PdfValidationError, validate_pdf


def enqueue_pdf(uploaded_file, *, user_id=None, guest_owner=None, email):
    """Validate and persist an upload, then add a durable queue row."""
    if not uploaded_file.filename or Path(uploaded_file.filename).suffix.lower() != ".pdf":
        raise PdfValidationError(
            "INVALID_FILE_FORMAT",
            "Invalid file format. Please upload a valid PDF file.",
            400,
        )
    uploaded_file.stream.seek(0, os.SEEK_END)
    size = uploaded_file.stream.tell()
    uploaded_file.stream.seek(0)
    if size > current_app.config["MAX_UPLOAD_SIZE_BYTES"]:
        raise PdfValidationError(
            "FILE_TOO_LARGE",
            "The uploaded file exceeds the maximum allowed size of 16 MB.",
            413,
        )
    if uploaded_file.stream.read(5) != b"%PDF-":
        raise PdfValidationError(
            "INVALID_FILE_FORMAT",
            "Invalid file format. Please upload a valid PDF file.",
            400,
        )
    uploaded_file.stream.seek(0)
    validate_pdf(uploaded_file.stream)
    uploaded_file.stream.seek(0)

    job_id = uuid4().hex
    configured_upload_dir = current_app.config.get("ANALYSIS_UPLOAD_DIR")
    upload_dir = (
        Path(configured_upload_dir)
        if configured_upload_dir
        else Path(current_app.root_path).parent / "uploads"
    )
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"job-{job_id}.pdf"
    uploaded_file.save(path)
    job = AnalysisJob(
        id=job_id,
        user_id=user_id,
        guest_owner=guest_owner,
        email=email,
        filename=Path(uploaded_file.filename).name[:255],
        pdf_path=str(path),
        status="queued",
    )
    try:
        db.session.add(job)
        db.session.commit()
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise
    return job


def guest_access_token(job_id):
    return URLSafeTimedSerializer(current_app.secret_key).dumps(
        job_id, salt="guest-analysis-report"
    )


def guest_job_from_token(job_id, token, max_age=48 * 60 * 60):
    if not token:
        return None
    try:
        token_job_id = URLSafeTimedSerializer(current_app.secret_key).loads(
            token,
            salt="guest-analysis-report",
            max_age=max_age,
        )
    except (BadSignature, SignatureExpired):
        return None
    if token_job_id != job_id:
        return None
    job = db.session.get(AnalysisJob, job_id)
    return job if job is not None and job.guest_owner else None


def guest_job_for_owner(job_id, owner_hash):
    job = db.session.get(AnalysisJob, job_id)
    if job is None or not owner_hash or not job.guest_owner:
        return None
    if not hmac.compare_digest(job.guest_owner, owner_hash):
        return None
    return job


def job_payload(job):
    payload = {
        "job_id": job.id,
        "status": job.status,
        "filename": job.filename,
        "email_sent": job.email_sent,
        "email_error": job.email_error,
        "error_code": job.error_code,
        "document_id": job.document_id,
    }
    if job.report_json:
        payload["report"] = json.loads(job.report_json)
    return payload


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
