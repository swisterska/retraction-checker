import re
from urllib.parse import unquote


DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "https://www.doi.org/",
    "http://www.doi.org/",
)


def normalize_doi(doi: str | None) -> str | None:
    """Return a consistently normalized DOI, or None for empty input."""
    if not isinstance(doi, str):
        return None

    value = doi.strip()

    if not value:
        return None

    value = unquote(value)

    # Remove common citation wrappers.
    value = value.strip("<>").strip()

    lowered = value.lower()

    for prefix in DOI_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix):]
            break

    value = value.strip()

    if value.lower().startswith("doi:"):
        value = value[4:].strip()

    # DOI values cannot contain whitespace.
    value = re.sub(r"\s+", "", value)

    # Remove common punctuation added after a DOI in citations.
    value = value.rstrip(".,;:")

    value = value.lower()

    return value or None
