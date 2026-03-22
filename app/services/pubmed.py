import time
from Bio import Entrez

# REQUIRED by NCBI
Entrez.email = "278448@student.pwr.edu.pl"


def pubmed_search(query: str) -> str | None:
    try:
        handle = Entrez.esearch(db="pubmed", term=query)
        record = Entrez.read(handle)
        handle.close()

        ids = record["IdList"]
        return ids[0] if ids else None

    except Exception as e:
        print("PubMed search error:", e)
        return None


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None

    doi = doi.strip().lower()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")

    return doi


def get_pmid(doi: str | None) -> str | None:
    doi = normalize_doi(doi)

    if not doi:
        return None

    # exact DOI match
    return pubmed_search(f'"{doi}"[DOI]')


def get_pmid_by_title(title: str | None) -> str | None:
    if not title:
        return None

    # exact title match
    return pubmed_search(f'"{title}"[Title]')


def enrich_with_pmid(references: list[dict]) -> list[dict]:
    enriched = []

    total = len(references)
    doi_found = 0

    for ref in references:
        doi = ref.get("doi")
        title = ref.get("title")

        pmid = None

        # DOI → PMID (primary)
        if doi:
            doi_found += 1
            pmid = get_pmid(doi)

        # fallback: strict title
        if not pmid and title:
            pmid = get_pmid_by_title(title)

        new_ref = ref.copy()
        new_ref["doi"] = doi
        new_ref["pmid"] = pmid

        enriched.append(new_ref)

        time.sleep(0.3)

    pmid_found = sum(1 for r in enriched if r.get("pmid"))

    print("\nPubMed enrichment statistics")
    print("Total references:", total)
    print("References with DOI:", doi_found)
    print("PMID found:", pmid_found)

    return enriched