import pandas as pd
import os
import time
from Bio import Entrez


# -------------------------
# AUTO UPDATE (PubMed)
# -------------------------

def should_update(path: str, max_age_hours: int = 24) -> bool:
    """
    Check if CSV should be refreshed.
    """
    if not os.path.exists(path):
        return True

    age = time.time() - os.path.getmtime(path)
    return age > max_age_hours * 3600


def update_retractions_from_pubmed(path: str, max_results: int = 5000):
    """
    Fetch retracted publications from PubMed and save as CSV.
    """

    Entrez.email = "278448@student.pwr.edu.pl"

    print("Updating retractions from PubMed...")

    try:
        # 1. search
        handle = Entrez.esearch(
            db="pubmed",
            term="Retracted Publication[PT]",
            retmax=max_results
        )
        record = Entrez.read(handle)
        handle.close()

        ids = record["IdList"]

        print("Found:", len(ids), "records")

        if not ids:
            print("No retractions found — skipping update")
            return

        # 2. fetch details
        handle = Entrez.efetch(
            db="pubmed",
            id=",".join(ids),
            rettype="medline",
            retmode="text"
        )

        text = handle.read()
        handle.close()

        # 3. extract DOIs
        dois = []

        for line in text.split("\n"):
            if line.startswith("AID") and "[doi]" in line:
                doi = (
                    line.replace("AID -", "")
                    .replace("[doi]", "")
                    .strip()
                    .lower()
                )
                dois.append(doi)

        if not dois:
            print("No DOI found in fetched data — skipping save")
            return

        # 4. save CSV
        df = pd.DataFrame({"doi": dois})
        df.to_csv(path, index=False)

        print("Saved retractions:", len(dois))

    except Exception as e:
        print("PubMed update failed:", e)
        print("Using existing CSV if available.")


# -------------------------
# MAIN SERVICE
# -------------------------

class RetractionService:
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path, encoding="utf-8-sig")

        # find DOI column
        doi_column = None
        for col in self.df.columns:
            if "doi" in col.lower():
                doi_column = col
                break

        if not doi_column:
            raise ValueError("No DOI column found in CSV")

        # normalize DOIs
        self.df["doi"] = (
            self.df[doi_column]
            .astype(str)
            .str.lower()
            .str.strip()
            .str.replace(r"\s+", "", regex=True)
            .str.replace("https://doi.org/", "", regex=False)
            .str.replace("http://doi.org/", "", regex=False)
            .str.replace("doi:", "", regex=False)
        )

        # remove invalid
        self.df = self.df[self.df["doi"] != "nan"]
        self.df = self.df[self.df["doi"] != "doi"]

        # debug
        print("Loaded DOIs:", list(self.df["doi"])[:5])

        # fast lookup
        self.doi_set = set(self.df["doi"])

    def is_retracted(self, doi: str | None) -> bool:
        if not doi:
            return False

        doi_norm = (
            doi.lower()
            .strip()
            .replace(" ", "")
            .replace("https://doi.org/", "")
            .replace("http://doi.org/", "")
            .replace("doi:", "")
        )

        return doi_norm in self.doi_set

    def mark_retracted(self, references: list[dict]) -> list[dict]:
        enriched = []

        for ref in references:
            doi = ref.get("doi")

            is_retracted = self.is_retracted(doi)

            new_ref = ref.copy()
            new_ref["retracted"] = is_retracted

            enriched.append(new_ref)

        return enriched