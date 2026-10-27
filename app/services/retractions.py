import pandas as pd
import requests
import os
import time



# AUTO UPDATE

def should_update(path: str, max_age_hours: int = 24) -> bool:
    if not os.path.exists(path):
        return True

    age = time.time() - os.path.getmtime(path)
    return age > max_age_hours * 3600


# FETCH FULL DATASET (Crossref API)

def update_retractions_from_api(save_path: str, rows_per_request: int = 1000):
    """
    Fetch ALL retracted publications using Crossref cursor pagination.
    """
    print("Updating FULL retractions dataset from Crossref API...")

    url = "https://api.crossref.org/works"

    cursor = "*"
    all_dois = set()
    total_fetched = 0

    while True:
        params = {
            "filter": "update-type:retraction",
            "rows": rows_per_request,
            "cursor": cursor
        }

        response = requests.get(url, params=params, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"API error: {response.status_code}")

        data = response.json()
        items = data["message"]["items"]

        if not items:
            break

        for item in items:
            doi = item.get("DOI")
            if doi:
                all_dois.add(doi.lower())

        total_fetched += len(items)
        print(f"Fetched: {total_fetched} | Unique DOIs: {len(all_dois)}")

        # next cursor
        cursor = data["message"]["next-cursor"]

        # safety break (optional)
        if total_fetched > 100000:
            print("Stopping early (safety limit)")
            break

    df = pd.DataFrame({"doi": list(all_dois)})
    df.to_csv(save_path, index=False)

    print(f"Saved FULL dataset: {len(df)} retractions → {save_path}")




def update_retractions_from_gitlab(save_path: str):
    print("Updating dataset from GitLab...")

    url = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"

    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Download failed: {response.status_code}")

    with open(save_path, "wb") as f:
        f.write(response.content)

    print("Saved retractions.csv from GitLab")


# MAIN SERVICE


class RetractionService:
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(
            csv_path,
            encoding="utf-8",
            encoding_errors="replace",
            low_memory=False,
        )

        doi_column = "OriginalPaperDOI"
        if doi_column not in self.df.columns:
            raise ValueError("OriginalPaperDOI column not found")

        # Normalize DOI values for reliable matching.
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

        self.df = self.df[
            ~self.df["doi"].isin(["nan", "doi", ""])
        ]

        # Keep the Reason column if it exists in the dataset.
        if "Reason" not in self.df.columns:
            self.df["Reason"] = None

        self.doi_set = set(self.df["doi"])

        # Build a DOI-to-reason lookup.
        self.reason_by_doi = (
            self.df.drop_duplicates(subset=["doi"], keep="first")
            .set_index("doi")["Reason"]
            .to_dict()
        )

        print("Loaded DOIs:", list(self.df["doi"])[:5])

    def normalize_doi(self, doi: str | None) -> str | None:
        if not doi:
            return None

        doi_norm = (
            doi.lower()
            .strip()
            .replace(" ", "")
            .replace("https://doi.org/", "")
            .replace("http://doi.org/", "")
            .replace("doi:", "")
        )

        return doi_norm or None

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
        enriched = []

        for ref in references:
            doi = ref.get("doi")
            is_retracted = self.is_retracted(doi)

            new_ref = ref.copy()
            new_ref["retracted"] = is_retracted
            new_ref["retraction_reason"] = (
                self.get_retraction_reason(doi)
                if is_retracted
                else None
            )

            enriched.append(new_ref)

        return enriched
