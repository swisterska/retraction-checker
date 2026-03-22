import pandas as pd


class RetractionService:
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path)

        # find DOI column
        doi_column = None
        for col in self.df.columns:
            if col.lower() == "doi":
                doi_column = col
                break

        if not doi_column:
            raise ValueError("No DOI column found in CSV")

        # normalize DOIs: lowercase, strip, remove spaces and common prefixes
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

        # usuń puste
        self.df = self.df[self.df["doi"] != "nan"]

        # DEBUG (na chwilę)
        print("Loaded DOIs:", list(self.df["doi"])[:5])

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