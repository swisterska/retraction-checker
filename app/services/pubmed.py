from Bio import Entrez
import time
import requests

# mandatory for PubMed API (user identification)
Entrez.email = "278448@student.pwr.edu.pl"


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
    Retrieve the PubMed ID (PMID) associated with a DOI.

    Args:
        doi (str | None): Digital Object Identifier.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    doi = normalize_doi(doi)

    if not doi:
        return None

    try:
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
        print("PubMed DOI search error:", e)
        return None


def get_pmid_by_title(title: str | None) -> str | None:
    """
    Retrieve PubMed ID (PMID) using article title.

    Args:
        title (str | None): Title of the publication.

    Returns:
        str | None: PMID if found, otherwise None.
    """

    if not title:
        return None

    try:
        handle = Entrez.esearch(
            db="pubmed",
            term=f"{title}[Title]"
        )

        record = Entrez.read(handle)
        handle.close()

        id_list = record["IdList"]

        if id_list:
            return id_list[0]

        return None

    except Exception as e:
        print("PubMed title search error:", e)
        return None
    

def get_doi_from_crossref(title: str | None, authors: list[str] | None = None) -> str | None:
    """
    Retrieve a DOI for a publication using the Crossref API.

    The function queries Crossref using the article title and optionally
    the first author name to improve search accuracy. It returns the first
    DOI found among the top search results.

    Args:
        title (str | None): Title of the publication.
        authors (list[str] | None): Optional list of author names.
            The first author is used to refine the search query.

    Returns:
        str | None: DOI string if found, otherwise None.

    Notes:
        - Uses the Crossref REST API: https://api.crossref.org
        - Only the first 5 results are checked.
        - Network or parsing errors are caught and logged.
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
    

def get_pmid_by_title_author(title: str | None, authors: list[str] | None) -> str | None:
    """
    Retrieve PubMed ID (PMID) using article title and first author.

    The function performs a PubMed search using the article title and
    the surname of the first author to increase the likelihood of
    retrieving the correct record.

    Args:
        title (str | None): Title of the publication.
        authors (list[str] | None): List of author names. The surname of
            the first author is used in the search query.

    Returns:
        str | None: PMID if a matching record is found, otherwise None.

    Notes:
        - Uses NCBI Entrez `esearch`.
        - Only the first PubMed ID from the search results is returned.
    """

    if not title:
        return None

    try:

        query = title

        if authors:
            first_author = authors[0].split()[-1]
            query += f" {first_author}"

        handle = Entrez.esearch(
            db="pubmed",
            term=query
        )

        record = Entrez.read(handle)
        handle.close()

        ids = record["IdList"]

        if ids:
            return ids[0]

        return None

    except Exception as e:
        print("PubMed title+author error:", e)
        return None


def get_pmid_by_author_keyword(authors: list[str] | None, title: str | None) -> str | None:
    """
    Retrieve PubMed ID (PMID) using author name and a title keyword.

    This function constructs a PubMed query using the surname of the
    first author and the first word from the title as a keyword.
    It serves as a last-resort fallback when DOI and title searches fail.

    Args:
        authors (list[str] | None): List of author names.
        title (str | None): Title of the publication.

    Returns:
        str | None: PMID if found, otherwise None.

    Notes:
        - The query format is: "<author>[Author] <keyword>".
        - Only the first result from PubMed is returned.
    """
    
    if not authors:
        return None

    try:
        author = authors[0].split()[-1]
        keyword = title.split()[0]

        query = f"{author}[Author] {keyword}"

        handle = Entrez.esearch(db="pubmed", term=query)

        record = Entrez.read(handle)
        handle.close()

        ids = record["IdList"]

        if ids:
            return ids[0]

        return None

    except Exception as e:
        print("Author search error:", e)
        return None
    
    
        
def enrich_with_pmid(references: list[dict]) -> list[dict]:
    """
    Enrich a list of bibliographic references with DOI and PubMed ID (PMID).

    The function attempts to identify a PubMed record for each reference
    using a sequence of increasingly permissive strategies:

    1. If a DOI is already present, search PubMed by DOI.
    2. If DOI is missing, attempt to recover it using the Crossref API.
    3. Search PubMed by exact title.
    4. Search PubMed by title and first author surname.
    5. Perform a fallback search using first author and title keyword.

    Each reference dictionary is copied and extended with two fields:
    `doi` and `pmid`.

    Args:
        references (list[dict]): List of reference dictionaries.
            Expected keys may include:
            - "title"
            - "authors"
            - "doi"

    Returns:
        list[dict]: List of enriched reference dictionaries containing:
            - original fields
            - "doi" (normalized or recovered DOI)
            - "pmid" (PubMed identifier if found)

    Side Effects:
        Prints summary statistics including:
        - total references processed
        - number of references with DOI
        - number of DOIs recovered from Crossref
        - number of PMIDs successfully identified

    Notes:
        - A short delay (`time.sleep(0.3)`) is used between queries
          to respect PubMed API rate limits.
        - Errors from API requests are caught and logged.
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
        if not pmid and title:
            pmid = get_pmid_by_title(title)

        # title + author
        if not pmid and title:
            pmid = get_pmid_by_title_author(title, authors)

        # author keyword
        if not pmid:
            pmid = get_pmid_by_author_keyword(authors, title)

        new_ref = ref.copy()
        new_ref["doi"] = doi
        new_ref["pmid"] = pmid

        enriched.append(new_ref)

        time.sleep(0.3)

    # statystyki liczymy z finalnych danych
    pmid_found = sum(1 for r in enriched if r["pmid"])
    missing_pmid = total - pmid_found

    print("\nPubMed enrichment statistics")
    print("Total references:", total)
    print("References with DOI:", doi_found)
    print("DOI recovered from Crossref:", doi_recovered)
    print("PMID found:", pmid_found)
    print("PMID missing:", missing_pmid)

    return enriched

