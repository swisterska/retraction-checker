
from datetime import datetime, timezone
from app.database import db


def utc_now():
    """Returns the current date and time in UTC.

    Using UTC ensures that timestamps are consistent across different time zones.
    """
    return datetime.now(timezone.utc)


class User(db.Model):
    """Store account details and email verification status for a user."""
    
    __bind_key__ = "users"
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)


class EmailVerificationToken(db.Model):
    """Store a user's hashed email confirmation token and its expiry time."""

    __bind_key__ = "users"
    __tablename__ = "email_verification_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


class PasswordResetToken(db.Model):
    """Store a user's hashed password reset token and its expiry time."""

    __bind_key__ = "users"
    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


class UploadedDocument(db.Model):
    """Store metadata about a PDF document uploaded by a user."""
    
    __tablename__ = "uploaded_documents"

    id = db.Column(db.Integer, primary_key=True)
    #ID of the user who uploaded the document
    user_id = db.Column(db.Integer, nullable=False, index=True)

    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_checked_at = db.Column(db.DateTime, default=utc_now, nullable=True)
    processing_status = db.Column(db.String(50), default="pending", nullable=False)

    #References extracted from the document
    references = db.relationship("ExtractedReference", back_populates="document", cascade="all, delete-orphan")

    #Watchlist entries for this document, allowing users to monitor its retraction status
    watch_entries = db.relationship("DocumentWatch", back_populates="document", cascade="all, delete-orphan")


class DocumentWatch(db.Model):
    """Track which users are monitoring the retraction status of a specific document."""
    
    __tablename__ = "document_watchlist"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_documents.id"), nullable=False, index=True)
    #Time when the user started watching the document
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "document_id", name="uq_document_watch_user_document"),
    )

    document = db.relationship("UploadedDocument", back_populates="watch_entries")


class ExtractedReference(db.Model):
    """Store bibliographic references extracted from uploaded documents."""

    __tablename__ = "extracted_references"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_documents.id"), nullable=False)
    #The raw reference text as extracted from the document, which may include formatting and other non-standard elements.
    raw_reference = db.Column(db.Text)
    title = db.Column(db.String(500))
    authors = db.Column(db.Text)
    year = db.Column(db.Integer)
    doi = db.Column(db.String(255))
    pmid = db.Column(db.String(50))

    #Allows to go from the reference back to the document it was extracted from, enabling queries that link references to their source documents.
    document = db.relationship("UploadedDocument", back_populates="references")
    
    detection_results = db.relationship("DetectionResult", back_populates="reference", cascade="all, delete-orphan")


class RetractedPublication(db.Model):
    """Store details about a publication listed as retracted."""

    __tablename__ = "retracted_publications"

    # Information about the retracted publication
    doi = db.Column(db.String(255), unique=True)
    pmid = db.Column(db.String(50))
    title = db.Column(db.String(500))

    # When the publication was officially retracted and the reason for the retraction.
    retraction_date = db.Column(db.Date)
    retraction_reason = db.Column(db.Text)

    # Source of the retraction information, such as a database or journal notice.
    source = db.Column(db.String(255))

    detection_results = db.relationship("DetectionResult", back_populates="retracted_publication")


class DetectionResult(db.Model):
    """Store the outcome of checking an extracted reference against known retracted publications."""

    __tablename__ = "detection_results"

    id = db.Column(db.Integer, primary_key=True)

    # The ID of the extracted reference that was checked.
    reference_id = db.Column(db.Integer, db.ForeignKey("extracted_references.id"), nullable=False)

    # Matching retracted publication, if any, and whether the reference was found to be retracted.
    retracted_publication_id = db.Column(db.Integer, db.ForeignKey("retracted_publications.id"))

    is_retracted = db.Column(db.Boolean, nullable=False)

    # General status of the verification; default is "not_verified"
    verification_status = db.Column(db.String(30), nullable=False, default="not_verified")

    
    verification_note = db.Column(db.Text)
    detection_method = db.Column(db.String(100))
    detected_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationships that allow easy navigation between the detection resultthe extracted reference, and the retracted publication.
    reference = db.relationship("ExtractedReference", back_populates="detection_results")
    retracted_publication = db.relationship("RetractedPublication", back_populates="detection_results")


class Notification(db.Model):
    """Store an in-app notification and its email status"""
    
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_documents.id"), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    email_sent = db.Column(db.Boolean, default=False, nullable=False)

    # Allows to naviagate from the notification to the document it is associated with.
    document = db.relationship("UploadedDocument")


class AnalysisJob(db.Model):
    """Store a PDF analysis job for the background worker.
    Worker will process the job, extract references, and check for retractions, even if user closes the browser or logs out. 
    The job will be marked as finished when the analysis is complete, and the user will be notified via email."""

    __tablename__ = "analysis_jobs"

    # Unique identifier for the job
    id = db.Column(db.String(32), primary_key=True)

    user_id = db.Column(db.Integer, nullable=True, index=True)
    guest_owner = db.Column(db.String(64), nullable=True, index=True)

    #Email where we send the notification when the job is finished and report is ready.
    email = db.Column(db.String(255), nullable=False)

    # PDF name and path to the uploaded document.
    filename = db.Column(db.String(255), nullable=False)
    pdf_path = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    error_code = db.Column(db.String(64), nullable=True)

    # Place for the saved document or guest report.
    document_id = db.Column(db.Integer, nullable=True)
    report_json = db.Column(db.Text, nullable=True)

    # Dates of creation, last update, and completion of the job. 
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)

    email_sent = db.Column(db.Boolean, nullable=False, default=False)
    email_error = db.Column(db.String(255), nullable=True)


class BackgroundTaskState(db.Model):
    """Store when a background task last completed successfully."""

    __tablename__ = "background_task_states"

    name = db.Column(db.String(80), primary_key=True)
    last_success_at = db.Column(db.DateTime, nullable=True)


