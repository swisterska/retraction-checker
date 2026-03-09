from Bio import Entrez
import time


# mandatory for Pubmed API (user identification)
Entrez.email = "278448@student.pwr.edu.pl"


def get_pmid(doi: str) -> str | None:
   
    """
    Returns PubMed ID (PMID) for a given DOI.
    If no PMID is found, returns None.
    """

    if not doi:
        return None

    try:
        # call PubMed API
        handle = Entrez.esearch(
            db="pubmed",
            term=f"{doi}[DOI]"
        )

        record = Entrez.read(handle)
        handle.close()

        id_list = record["IdList"]

        if id_list:
            return id_list[0]

        return None

    except Exception as e:
        print("PubMed error:", e)
        return None


def enrich_with_pmid(references: list[dict]) -> list[dict]:
    
    """
    For every reference adds PMID field.
    """

    enriched = []

    for ref in references:
        doi = ref.get("doi")

        pmid = get_pmid(doi)

        new_ref = ref.copy()
        new_ref["pmid"] = pmid

        enriched.append(new_ref)

        # API limit 
        time.sleep(0.3)

    return enriched
