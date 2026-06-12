// Human-readable ranges become the duration facet choices shown by Search UI.
export const DURATION_RANGES = [
  { from: 0, to: 3, name: "Under 3 seconds" },
  { from: 3, to: 5, name: "3 to 5 seconds" },
  { from: 5, to: 10, name: "5 to 10 seconds" },
  { from: 10, name: "10 seconds or longer" }
];

export const SEARCH_QUERY_CONFIG = {
  // Transcriptions are the only analyzed full-text field.
  search_fields: {
    generated_text: { weight: 3 }
  },
  // Return only fields required to build result cards.
  result_fields: {
    filename: { raw: {} },
    generated_text: {
      raw: {},
      snippet: { size: 180, fallback: true }
    },
    duration: { raw: {} },
    age: { raw: {} },
    gender: { raw: {} },
    accent: { raw: {} }
  },
  // Numeric duration uses ranges; demographic metadata uses exact values.
  facets: {
    duration: {
      type: "range",
      ranges: DURATION_RANGES
    },
    age: { type: "value", size: 20, sort: "value" },
    gender: { type: "value", size: 10, sort: "value" },
    accent: { type: "value", size: 30, sort: "value" }
  },
  // Disjunctive facets keep alternative choices visible while one is selected.
  disjunctiveFacets: ["duration", "age", "gender", "accent"]
};

// The Express proxy uses this allowlist to reject arbitrary browser filters.
export const ALLOWED_FILTER_FIELDS = new Set([
  "duration",
  "age",
  "gender",
  "accent"
]);

// Restrict page sizes to known values to bound Elasticsearch response sizes.
export const ALLOWED_RESULTS_PER_PAGE = new Set([10, 20, 50]);
