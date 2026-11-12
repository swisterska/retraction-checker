
from app.database import db
from app.models import (
    UploadedDocument,
    ExtractedReference,
    RetractedPublication,
    DetectionResult,
)
from app.services.doi import normalize_doi


def save_analysis_results(
    user_id: int,
    filename: str,
    references: list[dict],
    *,
    upload_date=None,
    last_checked_at=None,
    commit=True,
) -> int:
    """Atomically save a document, its references, and detection results."""

    try:
        document_fields = {
            "user_id": user_id,
            "filename": filename,
            "processing_status": "completed",
        }
        if upload_date is not None:
            document_fields["upload_date"] = upload_date
        if last_checked_at is not None:
            document_fields["last_checked_at"] = last_checked_at
        document = UploadedDocument(**document_fields)
        db.session.add(document)
        db.session.flush()

        for ref in references:
            doi = normalize_doi(ref.get("doi"))

            reference = ExtractedReference(
                document_id=document.id,
                raw_reference=ref.get("raw_reference"),
                title=ref.get("title"),
                authors=(
                    ", ".join(ref.get("authors", []))
                    if isinstance(ref.get("authors"), list)
                    else ref.get("authors")
                ),
                year=ref.get("year"),
                doi=doi,
                pmid=ref.get("pmid"),
            )
            db.session.add(reference)
            db.session.flush()

            retracted_publication = None

            if ref.get("retracted") and doi:
                reason = ref.get("retraction_reason")

                retracted_publication = (
                    db.session.query(RetractedPublication)
                    .filter_by(doi=doi)
                    .first()
                )

                if retracted_publication is None:
                    retracted_publication = RetractedPublication(
                        doi=doi,
                        pmid=ref.get("pmid"),
                        title=ref.get("title"),
                        retraction_reason=reason,
                        source="Retraction Watch",
                    )
                    db.session.add(retracted_publication)
                    db.session.flush()

                elif (
                    reason
                    and not retracted_publication.retraction_reason
                ):
                    retracted_publication.retraction_reason = reason

            verification_status = ref.get("verification_status")
            if verification_status not in {
                "retracted",
                "verified",
                "not_verified",
                "missing_doi",
            }:
                verification_status = (
                    "retracted"
                    if ref.get("retracted")
                    else "missing_doi" if not doi else "not_verified"
                )

            result = DetectionResult(
                reference_id=reference.id,
                retracted_publication_id=(
                    retracted_publication.id
                    if retracted_publication is not None
                    else None
                ),
                is_retracted=bool(ref.get("retracted")),
                verification_status=verification_status,
                verification_note=ref.get("verification_note"),
                detection_method=(
                    "DOI metadata match and Retraction Watch DOI check"
                ),
            )
            db.session.add(result)

        document_id = document.id
        if commit:
            db.session.commit()

        return document_id

    except Exception:
        db.session.rollback()
        raise
