export type ResultsFilter =
  | "all"
  | "retracted"
  | "verified"
  | "missing_doi"
  | "not_verified";
export type ResultsFilterSelection = ResultsFilter[];

type FilterableFinding = {
  doi: string | null;
  is_retracted: boolean | null;
  verification_status: string;
  title?: string | null;
  authors?: string | null;
  year?: number | null;
  pmid?: string | null;
};

export function filterFindings<T extends FilterableFinding>(
  findings: T[],
  filter: ResultsFilterSelection | ResultsFilter,
): T[] {
  const selectedFilters = Array.isArray(filter)
    ? filter.length
      ? filter
      : ["all"]
    : [filter];

  if (selectedFilters.includes("all")) {
    return findings;
  }

  const matches = new Set(selectedFilters);

  return findings.filter((item) => {
    if (matches.has("retracted") && item.is_retracted === true) {
      return true;
    }
    if (matches.has("verified") && item.verification_status === "verified") {
      return true;
    }
    if (
      matches.has("missing_doi") &&
      (!item.doi?.trim() || item.verification_status === "missing_doi")
    ) {
      return true;
    }
    if (
      matches.has("not_verified") &&
      item.verification_status === "not_verified"
    ) {
      return true;
    }
    return false;
  });
}

function normalizeSearchText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[\u2019']/g, "")
    .split(/\s+/)
    .map((part) =>
      part
        .replace(/^[^\p{L}\p{N}]+/gu, "")
        .replace(/[.,:;!?]+$/g, "")
        .replace(/[^\p{L}\p{N}/.-]+/gu, " ")
        .trim(),
    )
    .filter(Boolean)
    .join(" ");
}

function buildCitationText<T extends FilterableFinding>(item: T): string {
  const title = item.title?.trim();
  const authors = item.authors?.trim();
  const year = item.year != null ? String(item.year) : "";
  const doi = item.doi?.trim();

  return [title, authors, year, doi ? `DOI: ${doi}` : ""]
    .filter(Boolean)
    .join(" ");
}

export function searchFindings<T extends FilterableFinding>(
  findings: T[],
  query: string,
): T[] {
  const trimmed = query.trim();
  if (!trimmed) {
    return findings;
  }

  const normalizedQuery = normalizeSearchText(trimmed);
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);

  return findings.filter((item) => {
    const haystack = [
      item.title,
      item.authors,
      item.doi,
      item.pmid,
      item.year != null ? String(item.year) : "",
      item.title && item.authors ? `${item.title} ${item.authors}` : "",
      buildCitationText(item),
    ]
      .filter(Boolean)
      .join(" ");

    const normalizedHaystack = normalizeSearchText(haystack);

    return tokens.every((token) => normalizedHaystack.includes(token));
  });
}
