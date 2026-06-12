import express from "express";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ElasticsearchAPIConnector from "@elastic/search-ui-elasticsearch-connector";

import {
  ALLOWED_FILTER_FIELDS,
  ALLOWED_RESULTS_PER_PAGE,
  SEARCH_QUERY_CONFIG
} from "./search-config.js";

// ES modules do not expose __dirname, so derive it for the production dist path.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_PORT = 3000;

export function sanitizeSearchState(state = {}) {
  // Accept only bounded pagination values controlled by this application.
  const current = Number.isInteger(state.current) && state.current > 0
    ? state.current
    : 1;
  const resultsPerPage = ALLOWED_RESULTS_PER_PAGE.has(state.resultsPerPage)
    ? state.resultsPerPage
    : 10;
  const searchTerm = typeof state.searchTerm === "string"
    ? state.searchTerm.slice(0, 200)
    : "";
  // Discard unknown fields and cap values so the browser cannot construct
  // arbitrary Elasticsearch queries through the proxy.
  const filters = Array.isArray(state.filters)
    ? state.filters
        .filter(
          (filter) =>
            filter &&
            ALLOWED_FILTER_FIELDS.has(filter.field) &&
            Array.isArray(filter.values)
        )
        .map((filter) => ({
          field: filter.field,
          type: ["all", "any", "none"].includes(filter.type)
            ? filter.type
            : "all",
          values: filter.values.slice(0, 20)
        }))
    : [];

  return {
    current,
    resultsPerPage,
    searchTerm,
    filters,
    sortDirection: "",
    sortField: "",
    sortList: []
  };
}

export function createApp({
  connector,
  elasticsearchHost,
  elasticsearchIndex
}) {
  // Dependency injection keeps the Express routes independently testable.
  const app = express();
  // Avoid advertising the Express implementation in HTTP response headers.
  app.disable("x-powered-by");
  // Search requests are small JSON objects; reject unexpectedly large bodies.
  app.use(express.json({ limit: "256kb" }));

  // Report application health only when the private Elasticsearch dependency
  // can assign its primary shards.
  app.get("/api/health", async (_request, response) => {
    try {
      const healthResponse = await fetch(
        `${elasticsearchHost}/_cluster/health?wait_for_status=yellow&timeout=3s`
      );
      if (!healthResponse.ok) {
        throw new Error(`Elasticsearch returned ${healthResponse.status}`);
      }
      const health = await healthResponse.json();
      response.json({
        status: "ok",
        cluster: health.cluster_name,
        clusterStatus: health.status,
        index: elasticsearchIndex
      });
    } catch (error) {
      response.status(503).json({
        status: "error",
        message: "Elasticsearch is unavailable."
      });
    }
  });

  app.post("/api/search", async (request, response) => {
    try {
      // Ignore any browser-provided query configuration and use the server's
      // approved fields, facets, and result schema.
      const state = sanitizeSearchState(request.body?.state);
      const result = await connector.onSearch(state, SEARCH_QUERY_CONFIG);
      response.json(result);
    } catch (error) {
      console.error("Search request failed:", error);
      response.status(502).json({
        error: "Search request failed."
      });
    }
  });

  // Serve the Vite production build from the same process as the API proxy.
  const distPath = path.join(__dirname, "dist");
  app.use(express.static(distPath));
  // Send index.html for client-side routes while leaving /api errors intact.
  app.use((request, response, next) => {
    if (request.method !== "GET" || request.path.startsWith("/api/")) {
      next();
      return;
    }
    response.sendFile(path.join(distPath, "index.html"));
  });

  return app;
}

export function startServer() {
  // Environment variables let Docker address Elasticsearch by its service name.
  const port = Number(process.env.PORT || DEFAULT_PORT);
  const elasticsearchHost =
    process.env.ELASTICSEARCH_HOST || "http://localhost:9200";
  const elasticsearchIndex =
    process.env.ELASTICSEARCH_INDEX || "cv-transcriptions";

  // This connector runs server-side, keeping Elasticsearch off the public web.
  const connector = new ElasticsearchAPIConnector({
    host: elasticsearchHost,
    index: elasticsearchIndex
  });
  const app = createApp({
    connector,
    elasticsearchHost,
    elasticsearchIndex
  });

  return app.listen(port, "0.0.0.0", () => {
    console.log(`Search UI listening on http://0.0.0.0:${port}`);
  });
}

// Start listening only when this file is executed directly, not when tests
// import createApp or sanitizeSearchState.
const isEntrypoint =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isEntrypoint) {
  startServer();
}
