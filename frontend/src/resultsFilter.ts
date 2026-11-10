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
