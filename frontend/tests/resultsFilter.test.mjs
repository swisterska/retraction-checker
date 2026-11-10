import assert from "node:assert/strict";
import test from "node:test";
import { filterFindings, searchFindings } from "../src/resultsFilter.ts";

const findings = [
  {
    reference_id: 1,
    title: "Example article",
    authors: "Smith, A.",
    doi: "10.1234/example",
    is_retracted: true,
    verification_status: "retracted",
  },
  {
    reference_id: 2,
    title: "Verified paper",
    authors: "Brown, B.",
    doi: "10.1234/verified",
    is_retracted: false,
    verification_status: "verified",
  },
  {
    reference_id: 3,
    title: "Missing DOI article",
    authors: "Taylor, D.",
    doi: null,
    is_retracted: false,
    verification_status: "missing_doi",
  },
  {
    reference_id: 4,
    title: "No notice article",
    authors: "Jones, E.",
    doi: "   ",
    is_retracted: null,
    verification_status: "not_verified",
  },
];

test("all filter returns every finding", () => {
  assert.deepEqual(filterFindings(findings, "all"), findings);
});

test("retracted filter returns only retracted findings", () => {
  assert.deepEqual(
    filterFindings(findings, "retracted").map(
      ({ reference_id }) => reference_id,
    ),
    [1],
  );
});

test("missing DOI filter includes absent, blank, and explicitly missing DOI findings", () => {
  assert.deepEqual(
    filterFindings(findings, "missing_doi").map(
      ({ reference_id }) => reference_id,
    ),
    [3, 4],
  );
});

test("verified filter returns only confirmed references", () => {
  assert.deepEqual(
    filterFindings(findings, ["verified"]).map(
      ({ reference_id }) => reference_id,
    ),
    [2],
  );
});

test("no retraction notice found filter returns only neutral findings", () => {
  assert.deepEqual(
    filterFindings(findings, ["not_verified"]).map(
      ({ reference_id }) => reference_id,
    ),
    [4],
  );
});

test("multiple filters can be combined in the dropdown selection", () => {
  assert.deepEqual(
    filterFindings(findings, ["missing_doi", "not_verified"]).map(
      ({ reference_id }) => reference_id,
    ),
    [3, 4],
  );
});

test("reference search matches title, author, DOI and citation fragments", () => {
  assert.deepEqual(
    searchFindings(findings, "example").map(({ reference_id }) => reference_id),
    [1],
  );
  assert.deepEqual(
    searchFindings(findings, "brown").map(({ reference_id }) => reference_id),
    [2],
  );
  assert.deepEqual(
    searchFindings(findings, "10.1234/verified").map(
      ({ reference_id }) => reference_id,
    ),
    [2],
  );
  assert.deepEqual(
    searchFindings(
      findings,
      "Example article. Smith, A. DOI: 10.1234/example",
    ).map(({ reference_id }) => reference_id),
    [1],
  );
});
