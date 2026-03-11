from Bio import Entrez
import time
import requests

# mandatory for PubMed API 
Entrez.email = "278448@student.pwr.edu.pl"


def pubmed_search(query: str) -> str | None:
    """
    Perform a PubMed search and return the first matching PMID.

    Args:
        query (str): PubMed search query.

    Returns:
        str | None: First PMID found or None if no results are returned.

    Notes:
        Uses NCBI Entrez `esearch` endpoint.
    """

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
    """
    Normalize DOI string to a canonical format.

    Removes common prefixes such as URL forms or 'doi:' labels.

    Args:
        doi (str | None): DOI extracted from reference.

    Returns:
        str | None: Clean DOI or None if input is empty.
    """

    if not doi:
        return None

    doi = doi.strip().lower()

    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")

    return doi



def get_pmid(doi: str | None) -> str | None:
    """
    Retrieve PubMed ID (PMID) using a DOI.

    Args:
        doi (str | None): Digital Object Identifier.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    doi = normalize_doi(doi)

    if not doi:
        return None

    return pubmed_search(f"{doi}[DOI]")



def get_pmid_by_title(title: str | None) -> str | None:
    """
    Retrieve PMID using the article title.

    Args:
        title (str | None): Title of the publication.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    if not title:
        return None

    return pubmed_search(f"{title}[Title]")




def get_pmid_by_title_author(title: str | None, authors: list[str] | None) -> str | None:
    """
    Retrieve PMID using article title and first author surname.

    Args:
        title (str | None): Title of the publication.
        authors (list[str] | None): List of author names.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    if not title:
        return None

    query = title

    if authors:
        first_author = authors[0].split()[-1]
        query += f" {first_author}"

    return pubmed_search(query)




def get_pmid_by_author_keyword(authors: list[str] | None, title: str | None) -> str | None:
    """
    Retrieve PMID using author surname and a keyword from the title.

    This method is used as a last fallback when other search strategies fail.

    Args:
        authors (list[str] | None): List of author names.
        title (str | None): Title of the publication.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    if not authors or not title:
        return None

    author = authors[0].split()[-1]
    keyword = title.split()[0]

    query = f"{author}[Author] {keyword}"

    return pubmed_search(query)


def get_doi_from_crossref(title: str | None, authors: list[str] | None = None) -> str | None:
    """
    Retrieve DOI for a publication using the Crossref API.

    The search is based on the article title and optionally the
    first author name to improve accuracy.

    Args:
        title (str | None): Title of the publication.
        authors (list[str] | None): Optional list of authors.

    Returns:
        str | None: DOI if found, otherwise None.
    """

    if not title:
        return None

    try:
        url = "https://api.crossref.org/works"

        query = title
        if authors:
            query += " " + authors[0]

        params = {
            "query": query,
            "rows": 5
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()

        items = data["message"]["items"]

        for item in items:
            if "DOI" in item:
                return item["DOI"]

        return None

    except Exception as e:
        print("Crossref error:", e)
        return None


def enrich_with_pmid(references: list[dict]) -> list[dict]:
    """
    Enrich references with DOI and PubMed ID (PMID).

    The function applies a sequence of identification strategies:

    1. DOI to find PMID
    2. Title → Crossref → DOI → PMID
    3. Title to find PMID
    4. Title + author to find PMID
    5. Author + keyword to find PMID

    Args:
        references (list[dict]): List of reference dictionaries
            containing at least "title", "authors", or "doi".

    Returns:
        list[dict]: References enriched with:
            - doi
            - pmid
    """

    enriched = []

    total = len(references)
    doi_found = 0
    doi_recovered = 0

    for ref in references:

        doi = ref.get("doi")
        title = ref.get("title")
        authors = ref.get("authors")

        pmid = None

        # DOI from GROBID
        if doi:
            doi_found += 1
            pmid = get_pmid(doi)

        # recover DOI via Crossref
        if not doi and title:
            doi = get_doi_from_crossref(title, authors)

            if doi:
                doi_recovered += 1
                pmid = get_pmid(doi)

        # fallback title → PMID
        if not pmid:
            pmid = get_pmid_by_title(title)

        # title + author
        if not pmid:
            pmid = get_pmid_by_title_author(title, authors)

        # author keyword
        if not pmid:
            pmid = get_pmid_by_author_keyword(authors, title)

        new_ref = ref.copy()
        new_ref["doi"] = doi
        new_ref["pmid"] = pmid

        enriched.append(new_ref)

        time.sleep(0.3)

    pmid_found = sum(1 for r in enriched if r["pmid"])
    missing_pmid = total - pmid_found

    print("\nPubMed enrichment statistics")
    print("Total references:", total)
    print("References with DOI:", doi_found)
    print("DOI recovered from Crossref:", doi_recovered)
    print("PMID found:", pmid_found)
    print("PMID missing:", missing_pmid)

    return enriched