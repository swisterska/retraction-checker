
import logging
import os
import tempfile
import time

import pandas as pd
import requests

from app.services.doi import normalize_doi


logger = logging.getLogger(__name__)

RETRACTION_WATCH_URL = (
    "https://gitlab.com/crossref/retraction-watch-data/"
    "-/raw/main/retraction_watch.csv"
)

UPDATE_INTERVAL_HOURS = 24
REQUEST_TIMEOUT = 30


class RetractionDataError(RuntimeError):
    """Raised when no usable Retraction Watch dataset is available."""


def should_update(
    path: str,
    max_age_hours: int = UPDATE_INTERVAL_HOURS,
) -> bool:
    """Check whether the local dataset is missing or outdated."""

    if not os.path.isfile(path):
        logger.info(
            "Retraction Watch dataset does not exist: %s",
            path,
        )
        return True

    age = time.time() - os.path.getmtime(path)
    update_required = age >= max_age_hours * 3600

    if update_required:
        logger.info(
            "Retraction Watch dataset is outdated (age: %.2f hours).",
            age / 3600,
        )

    return update_required


def validate_retractions_csv(csv_path: str) -> None:
    """Validate the downloaded Retraction Watch CSV."""

    df = pd.read_csv(
        csv_path,
        encoding="utf-8",
        encoding_errors="replace",
        low_memory=False,
    )

    if "OriginalPaperDOI" not in df.columns:
        raise ValueError(
            "Invalid Retraction Watch dataset: "
            "OriginalPaperDOI column is missing."
        )

    normalized_dois = df["OriginalPaperDOI"].map(normalize_doi)
    valid_dois = normalized_dois.dropna()

    if valid_dois.empty:
        raise ValueError(
            "Invalid Retraction Watch dataset: "
            "no valid DOIs found."
        )

    logger.info(
        "Retraction Watch CSV validation successful: "
        "%d rows, %d unique valid DOIs.",
        len(df),
        valid_dois.nunique(),
    )


def update_retractions_from_gitlab(save_path: str) -> None:
    """
    Download, validate and atomically replace the local dataset.

    The existing dataset is preserved if downloading or validation fails.
    """

    start_time = time.perf_counter()

    logger.info("Starting Retraction Watch dataset download.")

    response = requests.get(
        RETRACTION_WATCH_URL,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    if not response.content:
        raise ValueError("GitLab returned an empty dataset.")

    directory = os.path.dirname(os.path.abspath(save_path))
    os.makedirs(directory, exist_ok=True)

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".csv",
            prefix=".retractions_",
            dir=directory,
            delete=False,
        ) as temporary_file:
            temporary_file.write(response.content)
            temporary_path = temporary_file.name

        validate_retractions_csv(temporary_path)

        os.replace(temporary_path, save_path)
        temporary_path = None

        elapsed_time = time.perf_counter() - start_time

        logger.info(
            "Retraction Watch dataset updated successfully: "
            "path=%s, size=%.2f MB, duration=%.2f seconds.",
            save_path,
            len(response.content) / (1024 * 1024),
            elapsed_time,
        )

    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def ensure_retractions_dataset(
    csv_path: str,
    max_age_hours: int = UPDATE_INTERVAL_HOURS,
) -> bool:
    """
    Ensure that a valid local dataset is available.

    Returns True if a new dataset was downloaded.
    Returns False if the existing dataset was reused.
    """

    if not should_update(csv_path, max_age_hours):
        logger.info(
            "Using existing Retraction Watch dataset: %s",
            csv_path,
        )
        return False

    try:
        update_retractions_from_gitlab(csv_path)
        return True

    except Exception as exc:
        if os.path.isfile(csv_path):
            logger.exception(
                "Retraction Watch update failed. "
                "Using the existing local dataset: %s",
                csv_path,
            )
            return False

        logger.exception(
            "Retraction Watch download failed and no local dataset exists."
        )
        raise RetractionDataError(
            "No usable Retraction Watch dataset is available."
        ) from exc


class RetractionService:
    def __init__(self, csv_path: str, can_verify_absence: bool = True):
        self.can_verify_absence = can_verify_absence
        start_time = time.perf_counter()

        logger.info(
            "Loading Retraction Watch dataset from: %s",
            csv_path,
        )

        try:
            self.df = pd.read_csv(
                csv_path,
                encoding="utf-8",
                encoding_errors="replace",
                low_memory=False,
            )
        except (OSError, pd.errors.ParserError, UnicodeError) as exc:
            logger.exception("Could not load the Retraction Watch dataset.")
            raise RetractionDataError(
                "The Retraction Watch dataset could not be loaded."
            ) from exc

        doi_column = "OriginalPaperDOI"

        if doi_column not in self.df.columns:
            logger.error(
                "Retraction Watch dataset is missing column: %s",
                doi_column,
            )
            raise RetractionDataError(
                "The Retraction Watch dataset is missing its DOI column."
            )

        self.df["doi"] = self.df[doi_column].map(normalize_doi)
        self.df = self.df[self.df["doi"].notna()].copy()

        if self.df.empty:
            logger.error(
                "Retraction Watch dataset contains no valid DOIs."
            )
            raise RetractionDataError(
                "Retraction Watch dataset contains no valid DOIs."
            )

        if "Reason" not in self.df.columns:
            self.df["Reason"] = None

        self.doi_set = set(self.df["doi"])

        self.reason_by_doi = (
            self.df.drop_duplicates(subset=["doi"], keep="first")
            .set_index("doi")["Reason"]
            .to_dict()
        )

        elapsed_time = time.perf_counter() - start_time

        logger.info(
            "Retraction Watch dataset loaded: "
            "rows=%d, unique_dois=%d, duration=%.2f seconds.",
            len(self.df),
            len(self.doi_set),
            elapsed_time,
        )

    def normalize_doi(self, doi: str | None) -> str | None:
        return normalize_doi(doi)

    def is_retracted(self, doi: str | None) -> bool:
        doi_norm = self.normalize_doi(doi)
        return doi_norm in self.doi_set if doi_norm else False

    def get_retraction_reason(self, doi: str | None) -> str | None:
        doi_norm = self.normalize_doi(doi)

        if not doi_norm:
            return None

        reason = self.reason_by_doi.get(doi_norm)

        if pd.isna(reason) or not reason:
            return None

        return str(reason).strip()

    def mark_retracted(self, references: list[dict]) -> list[dict]:
        start_time = time.perf_counter()

        enriched = []
        retracted_count = 0

        for ref in references:
            doi = ref.get("doi")
            doi_identity_verified = ref.get("doi_identity_verified") is True
            doi_is_listed = self.is_retracted(doi)
            is_retracted = doi_identity_verified and doi_is_listed

            if is_retracted:
                retracted_count += 1

            new_ref = ref.copy()
            new_ref["retracted"] = is_retracted
            if is_retracted:
                new_ref["verification_status"] = "retracted"
            elif self.normalize_doi(doi):
                if not doi_identity_verified:
                    new_ref["verification_status"] = "not_verified"
                    if doi_is_listed:
                        new_ref["verification_note"] = (
                            "This DOI appears in Retraction Watch, but its match "
                            "to the citation could not be confirmed. Review it manually."
                        )
                    else:
                        new_ref.setdefault(
                            "verification_note",
                            "The DOI could not be confirmed against the citation title.",
                        )
                elif self.can_verify_absence:
                    new_ref["verification_status"] = "verified"
                    new_ref["verification_note"] = None
                else:
                    new_ref["verification_status"] = "not_verified"
                    new_ref["verification_note"] = (
                        "The Retraction Watch data was not current, so absence "
                        "of a retraction could not be confirmed."
                    )
            else:
                new_ref["verification_status"] = "missing_doi"
                new_ref["verification_note"] = None
            new_ref["retraction_reason"] = (
                self.get_retraction_reason(doi)
                if is_retracted
                else None
            )

            enriched.append(new_ref)

        elapsed_time = time.perf_counter() - start_time

        logger.info(
            "Retraction screening completed: "
            "references=%d, retracted=%d, duration=%.2f seconds.",
            len(references),
            retracted_count,
            elapsed_time,
        )

        return enriched
