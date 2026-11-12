"""Daily checks for saved references that were previously verified."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.database import db
from app.models import (
    BackgroundTaskState,
    DetectionResult,
    DocumentWatch,
    ExtractedReference,
    Notification,
    RetractedPublication,
    UploadedDocument,
)
from app.run_grobid_pipeline import CSV_PATH
from app.services.doi import normalize_doi
from app.services.retractions import RetractionService, ensure_retractions_dataset


TASK_NAME = "daily_retraction_monitor"
WATCHLIST_REFRESH_HOUR = 7
WATCHLIST_TIMEZONE = ZoneInfo("Europe/Warsaw")
ALERT_PREFIX = "A cited reference is now retracted:"


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def should_run_watchlist_refresh(*, now=None, target_hour=WATCHLIST_REFRESH_HOUR):
    """Run at 7 a.m. Warsaw time and catch up if the app starts later that day."""
    now = now or datetime.now(timezone.utc)
    local_now = _as_utc(now).astimezone(WATCHLIST_TIMEZONE)
    return local_now.hour >= target_hour


def check_saved_references(app, *, now=None, dataset_path=CSV_PATH):
    """Update verified references that have since appeared in Retraction Watch.

    Returns the number of newly retracted references. Only a successful dataset
    load advances the persistent schedule marker, so failures can be retried.
    """
    now = _as_utc(now or datetime.now(timezone.utc))

    with app.app_context():
        state = db.session.get(BackgroundTaskState, TASK_NAME)
        if state and state.last_success_at:
            last_success_date = _as_utc(state.last_success_at).astimezone(
                WATCHLIST_TIMEZONE
            ).date()
            if last_success_date == now.astimezone(WATCHLIST_TIMEZONE).date():
                return 0

        ensure_retractions_dataset(dataset_path)
        service = RetractionService(dataset_path)
        watched_documents = (
            db.session.query(DocumentWatch, UploadedDocument)
            .join(
                UploadedDocument,
                (DocumentWatch.document_id == UploadedDocument.id)
                & (DocumentWatch.user_id == UploadedDocument.user_id),
            )
            .filter(DocumentWatch.is_active.is_(True))
            .all()
        )
        for watch_entry, document in watched_documents:
            watch_entry.last_checked_at = now
            document.last_checked_at = now

        candidates = (
            db.session.query(DetectionResult, ExtractedReference, UploadedDocument)
            .join(ExtractedReference, DetectionResult.reference_id == ExtractedReference.id)
            .join(UploadedDocument, ExtractedReference.document_id == UploadedDocument.id)
            .join(
                DocumentWatch,
                (DocumentWatch.document_id == UploadedDocument.id)
                & (DocumentWatch.user_id == UploadedDocument.user_id)
                & (DocumentWatch.is_active.is_(True)),
            )
            .filter(
                DetectionResult.verification_status == "verified",
                DetectionResult.is_retracted.is_(False),
                ExtractedReference.doi.isnot(None),
            )
            .all()
        )

        changed = 0
        for result, reference, document in candidates:
            doi = normalize_doi(reference.doi)
            if not doi or not service.is_retracted(doi):
                continue

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

            result.is_retracted = True
            result.verification_status = "retracted"
            result.retracted_publication_id = publication.id
            result.detection_method = "Daily Retraction Watch status check"
            result.detected_at = now

            db.session.add(Notification(
                user_id=document.user_id,
                document_id=document.id,
                message=(
                    f"{ALERT_PREFIX} “{reference.title or doi}” in "
                    f"“{document.filename}” (DOI: {doi})."
                ),
            ))
            changed += 1

        if state is None:
            state = BackgroundTaskState(name=TASK_NAME)
            db.session.add(state)
        state.last_success_at = now
        db.session.commit()
        return changed
