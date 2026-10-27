
from datetime import datetime, timezone

from app.database import db


def utc_now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    documents = db.relationship(
        "UploadedDocument",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UploadedDocument(db.Model):
    __tablename__ = "uploaded_documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
    )
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=utc_now, nullable=False)
    processing_status = db.Column(
        db.String(50),
        default="pending",
        nullable=False,
    )

    user = db.relationship("User", back_populates="documents")
    references = db.relationship(
        "ExtractedReference",
        back_populates="document",
        cascade="all, delete-orphan",
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
        db.ForeignKey("users.id"),
        nullable=False,
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

    user = db.relationship("User", backref="notifications")
    document = db.relationship("UploadedDocument")


