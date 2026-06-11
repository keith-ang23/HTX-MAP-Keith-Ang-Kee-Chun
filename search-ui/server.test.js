import assert from "node:assert/strict";
import test from "node:test";
import request from "supertest";

import { createApp, sanitizeSearchState } from "./server.js";

test("sanitizeSearchState allows only approved search fields and limits", () => {
  const state = sanitizeSearchState({
    current: 2,
    resultsPerPage: 1000,
    searchTerm: "a".repeat(250),
    filters: [
      { field: "accent", type: "any", values: ["singapore"] },
      { field: "private_field", type: "all", values: ["secret"] }
    ]
  });

  assert.equal(state.current, 2);
  assert.equal(state.resultsPerPage, 10);
  assert.equal(state.searchTerm.length, 200);
  assert.deepEqual(state.filters, [
    { field: "accent", type: "any", values: ["singapore"] }
  ]);
});

test("POST /api/search uses the server-owned query configuration", async () => {
  let capturedState;
  let capturedConfig;
  const connector = {
    async onSearch(state, config) {
      capturedState = state;
      capturedConfig = config;
      return {
        results: [],
        facets: {},
        totalResults: 0,
        totalPages: 0
      };
    }
  };
  const app = createApp({
    connector,
    elasticsearchHost: "http://elasticsearch.test",
    elasticsearchIndex: "cv-transcriptions"
  });

  const response = await request(app)
    .post("/api/search")
    .send({
      state: {
        searchTerm: "hello",
        current: 1,
        resultsPerPage: 20,
        filters: []
      },
      queryConfig: {
        search_fields: {
          unauthorized_field: {}
        }
      }
    });

  assert.equal(response.status, 200);
  assert.equal(capturedState.searchTerm, "hello");
  assert.deepEqual(Object.keys(capturedConfig.search_fields), ["generated_text"]);
  assert.equal(capturedConfig.result_fields.filename.raw instanceof Object, true);
});
