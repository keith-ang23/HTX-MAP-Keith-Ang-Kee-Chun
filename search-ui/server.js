import express from "express";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ElasticsearchAPIConnector from "@elastic/search-ui-elasticsearch-connector";

import {
  ALLOWED_FILTER_FIELDS,
  ALLOWED_RESULTS_PER_PAGE,
  SEARCH_QUERY_CONFIG
} from "./search-config.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_PORT = 3000;

export function sanitizeSearchState(state = {}) {
  const current = Number.isInteger(state.current) && state.current > 0
    ? state.current
    : 1;
  const resultsPerPage = ALLOWED_RESULTS_PER_PAGE.has(state.resultsPerPage)
    ? state.resultsPerPage
    : 10;
  const searchTerm = typeof state.searchTerm === "string"
    ? state.searchTerm.slice(0, 200)
    : "";
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
  const app = express();
  app.disable("x-powered-by");
  app.use(express.json({ limit: "256kb" }));

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

  const distPath = path.join(__dirname, "dist");
  app.use(express.static(distPath));
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
  const port = Number(process.env.PORT || DEFAULT_PORT);
  const elasticsearchHost =
    process.env.ELASTICSEARCH_HOST || "http://localhost:9200";
  const elasticsearchIndex =
    process.env.ELASTICSEARCH_INDEX || "cv-transcriptions";

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

const isEntrypoint =
  process.argv[1] &&
  import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isEntrypoint) {
  startServer();
}
