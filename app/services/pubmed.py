
import logging
import os
import time

from Bio import Entrez
from dotenv import load_dotenv

from app.services.doi import normalize_doi


load_dotenv()

logger = logging.getLogger(__name__)

# NCBI configuration
Entrez.email = os.getenv("NCBI_EMAIL")
Entrez.timeout = 20
Entrez.max_tries = 2

PUBMED_REQUEST_DELAY = 0.34


def pubmed_search(query: str) -> str | None:
    """Search PubMed and return the first matching PMID."""

    handle = None

    try:
        handle = Entrez.esearch(
            db="pubmed",
            term=query,
        )

        record = Entrez.read(handle)
        ids = record.get("IdList", [])

        return str(ids[0]) if ids else None

    except Exception:
        logger.exception(
            "PubMed search failed for query: %s",
            query,
        )
        return None

    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                logger.warning(
                    "Could not close PubMed response handle."
                )

        time.sleep(PUBMED_REQUEST_DELAY)


def get_pmid(doi: str | None) -> str | None:
    """Find a PubMed ID using an exact DOI search."""

    normalized_doi = normalize_doi(doi)

    if not normalized_doi:
        return None

    return pubmed_search(
        f'"{normalized_doi}"[DOI]'
    )


def get_pmid_by_title(title: str | None) -> str | None:
    """Find a PubMed ID using an exact title search."""

    if not isinstance(title, str) or not title.strip():
        return None

    return pubmed_search(
        f'"{title.strip()}"[Title]'
    )


def enrich_with_pmid(references: list[dict]) -> list[dict]:
    """
    Enrich references with PubMed IDs.

    DOI is the primary search method.
    Exact title matching is used as a fallback.
    """

    start_time = time.perf_counter()

    enriched = []

    total = len(references)
    doi_found = 0
    doi_matches = 0
    title_matches = 0

    logger.info(
        "Starting PubMed enrichment for %d references.",
        total,
    )

    for ref in references:
        doi = normalize_doi(ref.get("doi"))
        title = ref.get("title")

        pmid = None

        # DOI → PMID (primary)
        if doi:
            doi_found += 1
            pmid = get_pmid(doi)

            if pmid:
                doi_matches += 1

        # Fallback: exact title
        if not pmid and title:
            pmid = get_pmid_by_title(title)

            if pmid:
                title_matches += 1

        new_ref = ref.copy()
        new_ref["doi"] = doi
        new_ref["pmid"] = pmid

        enriched.append(new_ref)

    pmid_found = sum(
        1 for ref in enriched if ref.get("pmid")
    )

    elapsed_time = time.perf_counter() - start_time

    logger.info(
        "PubMed enrichment completed: "
        "total=%d, references_with_doi=%d, "
        "doi_matches=%d, title_matches=%d, "
        "pmid_found=%d, duration=%.2fs",
        total,
        doi_found,
        doi_matches,
        title_matches,
        pmid_found,
        elapsed_time,
    )

    return enriched
