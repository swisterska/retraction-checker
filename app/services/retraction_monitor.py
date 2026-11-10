"""Daily checks for saved references that were previously verified."""

from datetime import datetime, timedelta, timezone

from app.database import db
from app.models import (
    BackgroundTaskState,
    DetectionResult,
    ExtractedReference,
    Notification,
    RetractedPublication,
    UploadedDocument,
)
from app.run_grobid_pipeline import CSV_PATH
from app.services.doi import normalize_doi
from app.services.retractions import RetractionService, ensure_retractions_dataset


TASK_NAME = "daily_retraction_monitor"
CHECK_INTERVAL = timedelta(hours=24)
ALERT_PREFIX = "A cited reference is now retracted:"


def check_saved_references(app, *, now=None, dataset_path=CSV_PATH):
    """Update verified references that have since appeared in Retraction Watch.

    Returns the number of newly retracted references. Only a successful dataset
    load advances the persistent schedule marker, so failures can be retried.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    with app.app_context():
        state = db.session.get(BackgroundTaskState, TASK_NAME)
        if state and state.last_success_at:
            last_success = state.last_success_at
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=timezone.utc)
            if now - last_success < CHECK_INTERVAL:
                return 0

        ensure_retractions_dataset(dataset_path)
        service = RetractionService(dataset_path)
        candidates = (
            db.session.query(DetectionResult, ExtractedReference, UploadedDocument)
            .join(ExtractedReference, DetectionResult.reference_id == ExtractedReference.id)
            .join(UploadedDocument, ExtractedReference.document_id == UploadedDocument.id)
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
