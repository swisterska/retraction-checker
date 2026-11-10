
from datetime import datetime, timezone

from app.database import db


def utc_now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __bind_key__ = "users"
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)


class EmailVerificationToken(db.Model):
    __bind_key__ = "users"
    __tablename__ = "email_verification_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)



class UploadedDocument(db.Model):
    __tablename__ = "uploaded_documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        nullable=False,
        index=True,
    )

    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=utc_now, nullable=False)
    processing_status = db.Column(
        db.String(50),
        default="pending",
        nullable=False,
    )

    references = db.relationship(
        "ExtractedReference",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    watch_entries = db.relationship(
        "DocumentWatch",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentWatch(db.Model):
    __tablename__ = "document_watchlist"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_documents.id"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "document_id", name="uq_document_watch_user_document"),
    )

    document = db.relationship(
        "UploadedDocument",
        back_populates="watch_entries",
    )


class ExtractedReference(db.Model):
    __tablename__ = "extracted_references"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_documents.id"),
        nullable=False,
    )
    raw_reference = db.Column(db.Text)
    title = db.Column(db.String(500))
    authors = db.Column(db.Text)
    year = db.Column(db.Integer)
    doi = db.Column(db.String(255))
    pmid = db.Column(db.String(50))

    document = db.relationship(
        "UploadedDocument",
        back_populates="references",
    )
    detection_results = db.relationship(
        "DetectionResult",
        back_populates="reference",
        cascade="all, delete-orphan",
    )


class RetractedPublication(db.Model):
    __tablename__ = "retracted_publications"

    id = db.Column(db.Integer, primary_key=True)
    doi = db.Column(db.String(255), unique=True)
    pmid = db.Column(db.String(50))
    title = db.Column(db.String(500))
    retraction_date = db.Column(db.Date)
    retraction_reason = db.Column(db.Text)
    source = db.Column(db.String(255))

    detection_results = db.relationship(
        "DetectionResult",
        back_populates="retracted_publication",
    )


class DetectionResult(db.Model):
    __tablename__ = "detection_results"

    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(
        db.Integer,
        db.ForeignKey("extracted_references.id"),
        nullable=False,
    )
    retracted_publication_id = db.Column(
        db.Integer,
        db.ForeignKey("retracted_publications.id"),
    )
    is_retracted = db.Column(db.Boolean, nullable=False)
    verification_status = db.Column(
        db.String(30),
        nullable=False,
        default="not_verified",
    )
    verification_note = db.Column(db.Text)
    detection_method = db.Column(db.String(100))
    detected_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    reference = db.relationship(
        "ExtractedReference",
        back_populates="detection_results",
    )
    retracted_publication = db.relationship(
        "RetractedPublication",
        back_populates="detection_results",
    )


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        nullable=False,
        index=True,
    )

    document_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_documents.id"),
        nullable=True,
    )
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    email_sent = db.Column(db.Boolean, default=False, nullable=False)

    document = db.relationship("UploadedDocument")


class AnalysisJob(db.Model):
    """Durable queue entry for an analysis that outlives a browser request."""

    __tablename__ = "analysis_jobs"

    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    guest_owner = db.Column(db.String(64), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    pdf_path = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    error_code = db.Column(db.String(64), nullable=True)
    document_id = db.Column(db.Integer, nullable=True)
    report_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)
    email_sent = db.Column(db.Boolean, nullable=False, default=False)
    email_error = db.Column(db.String(255), nullable=True)


class BackgroundTaskState(db.Model):
    """Persistent schedule markers for work performed by the single worker."""

    __tablename__ = "background_task_states"

    name = db.Column(db.String(80), primary_key=True)
    last_success_at = db.Column(db.DateTime, nullable=True)


