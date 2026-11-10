"""Resolve DOI metadata and compare it with the extracted citation."""

from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import logging
import re
import unicodedata
from urllib.parse import quote

import requests

from app.services.doi import normalize_doi


logger = logging.getLogger(__name__)
DOI_RESOLVER_URL = "https://doi.org/"
DOI_METADATA_TIMEOUT = (3, 8)
DOI_METADATA_ACCEPT = "application/vnd.citationstyles.csl+json"
MAX_CONCURRENT_DOI_LOOKUPS = 5
EDITORIAL_TITLE_PREFIX = re.compile(
    r"^(?:retraction(?: notice)?|retracted|correction|erratum|corrigendum)\s*:\s*",
    re.IGNORECASE,
)


def _normalize_title(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def _title_variants(value: str | None) -> set[str]:
    normalized = _normalize_title(value)
    if not normalized or not isinstance(value, str):
        return {normalized} if normalized else set()
    editorial_prefix_match = EDITORIAL_TITLE_PREFIX.match(
        unicodedata.normalize("NFKC", value).strip()
    )
    if not editorial_prefix_match:
        return {normalized}
    without_prefix = value[editorial_prefix_match.end():]
    return {normalized, _normalize_title(without_prefix)}


def titles_match(citation_title: str | None, metadata_title: str | None) -> bool:
    """Return true only when normalized citation titles are very similar."""
    citation_variants = _title_variants(citation_title)
    metadata_variants = _title_variants(metadata_title)
    if not citation_variants or not metadata_variants:
        return False
    for citation in citation_variants:
        for metadata in metadata_variants:
            if citation == metadata:
                return True
            citation_tokens = set(citation.split())
            metadata_tokens = set(metadata.split())
            overlap = len(citation_tokens & metadata_tokens) / max(
                len(citation_tokens), len(metadata_tokens)
            )
            similarity = SequenceMatcher(None, citation, metadata).ratio()
            if similarity >= 0.9 and overlap >= 0.9:
                return True
    return False


def _first_surname(authors) -> str | None:
    if not authors:
        return None
    first = authors[0] if isinstance(authors, list) else str(authors).split(",", 1)[0]
    if isinstance(first, dict):
        first = first.get("family") or first.get("name")
    if not isinstance(first, str):
        return None
    words = _normalize_title(first).split()
    if not words:
        return None
    if len(words) > 1 and len(words[-1]) == 1:
        return words[0]
    return words[-1]


def get_doi_metadata(doi: str) -> dict | None:
    """Retrieve DOI metadata using DOI content negotiation."""
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None

    url = DOI_RESOLVER_URL + quote(normalized_doi, safe="/")
    try:
        response = requests.get(
            url,
            headers={"Accept": DOI_METADATA_ACCEPT},
            timeout=DOI_METADATA_TIMEOUT,
        )
        if response.status_code == 404:
            return {"_lookup_error": "not_found"}
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.info("Could not resolve metadata for DOI %s: %s", normalized_doi, exc)
        return None

    return payload if isinstance(payload, dict) else None


def _check_metadata_match(
    doi: str,
    citation_title: str | None,
    metadata: dict | None,
    citation_authors=None,
) -> tuple[bool, str | None]:
    if not normalize_doi(doi):
        return False, None
    if not _normalize_title(citation_title):
        return False, "The citation title could not be read, so the DOI could not be checked."
    if metadata is None:
        return False, "Publication metadata for this DOI could not be retrieved."
    lookup_error = metadata.get("_lookup_error")
    if lookup_error == "not_found":
        return False, "This DOI was not found by the DOI resolver. Check the citation."
    if lookup_error:
        return False, "DOI metadata could not be checked right now. Please try again later."

    normalized_doi = normalize_doi(doi)
    resolved_doi = normalize_doi(metadata.get("DOI") or metadata.get("doi"))
    if resolved_doi != normalized_doi:
        return False, "The DOI resolver did not confirm this DOI."

    metadata_title = metadata.get("title")
    if isinstance(metadata_title, list):
        metadata_title = metadata_title[0] if metadata_title else None
    if not isinstance(metadata_title, str) or not metadata_title.strip():
        return False, "The DOI record does not include a title to compare."
    if not titles_match(citation_title, metadata_title):
        return False, "The title linked to this DOI does not match the citation title."

    citation_first_author = _first_surname(citation_authors)
    metadata_first_author = _first_surname(metadata.get("author"))
    if (
        citation_first_author
        and metadata_first_author
        and citation_first_author != metadata_first_author
    ):
        return False, "The first author linked to this DOI does not match the citation."
    return True, None


def verify_doi_identity(
    doi: str | None,
    citation_title: str | None,
    citation_authors=None,
) -> tuple[bool, str | None]:
    """Check that the metadata resolved from a DOI describes the citation."""
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return False, None
    return _check_metadata_match(
        normalized_doi,
        citation_title,
        get_doi_metadata(normalized_doi),
        citation_authors,
    )


def verify_references_doi_identity(references: list[dict]) -> list[dict]:
    """Add DOI identity results to references, resolving unique DOIs in parallel."""
    unique_dois = list(dict.fromkeys(
        normalized
        for normalized in (normalize_doi(ref.get("doi")) for ref in references)
        if normalized
    ))
    metadata_by_doi: dict[str, dict | None] = {}
    if unique_dois:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOI_LOOKUPS) as executor:
            metadata_by_doi.update(zip(unique_dois, executor.map(get_doi_metadata, unique_dois)))

    verified_references = []
    for reference in references:
        item = reference.copy()
        doi = normalize_doi(item.get("doi"))
        item["doi_identity_verified"] = False
        item["verification_note"] = None
        if not doi:
            verified_references.append(item)
            continue

        title = item.get("title")
        is_verified, note = _check_metadata_match(
            doi,
            title,
            metadata_by_doi.get(doi),
            item.get("authors"),
        )
        item["doi_identity_verified"] = is_verified
        item["verification_note"] = note
        verified_references.append(item)

    return verified_references
