
from app.database import db
from app.models import (
    UploadedDocument,
    ExtractedReference,
    RetractedPublication,
    DetectionResult,
)


def save_analysis_results(user_id: int, filename: str, references: list[dict]):
    """Save an analysed document, its references, and detection results."""

    document = UploadedDocument(
        user_id=user_id,
        filename=filename,
        processing_status="completed",
    )
    db.session.add(document)
    db.session.flush()

    for ref in references:
        reference = ExtractedReference(
            document_id=document.id,
            raw_reference=ref.get("raw_reference"),
            title=ref.get("title"),
            authors=", ".join(ref.get("authors", []))
            if isinstance(ref.get("authors"), list)
            else ref.get("authors"),
            year=ref.get("year"),
            doi=ref.get("doi"),
            pmid=ref.get("pmid"),
        )
        db.session.add(reference)
        db.session.flush()

        retracted_publication = None

        if ref.get("retracted") and ref.get("doi"):
            doi = ref["doi"].strip().lower()
            reason = ref.get("retraction_reason")

            retracted_publication = RetractedPublication.query.filter_by(
                doi=doi
            ).first()

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
            elif reason and not retracted_publication.retraction_reason:
                # Fill in the reason if the publication already exists
                # but its reason has not been saved yet.
                retracted_publication.retraction_reason = reason

        result = DetectionResult(
            reference_id=reference.id,
            retracted_publication_id=(
                retracted_publication.id
                if retracted_publication
                else None
            ),
            is_retracted=bool(ref.get("retracted")),
            detection_method="DOI match against Retraction Watch dataset",
        )
        db.session.add(result)

    db.session.commit()
    return document.id
