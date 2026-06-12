import React from "react";
import { createRoot } from "react-dom/client";
import {
  ErrorBoundary,
  Facet,
  Paging,
  SearchBox,
  SearchProvider,
  WithSearch
} from "@elastic/react-search-ui";
import { ApiProxyConnector } from "@elastic/search-ui-elasticsearch-connector";
import "@elastic/react-search-ui-views/lib/styles/styles.css";

import { SEARCH_QUERY_CONFIG } from "../search-config.js";
import "./styles.css";

// The browser talks only to Express at /api, never directly to Elasticsearch.
const connector = new ApiProxyConnector({ basePath: "/api" });

// SearchProvider owns query state, URL synchronization, and API requests.
const searchConfig = {
  apiConnector: connector,
  searchQuery: SEARCH_QUERY_CONFIG,
  initialState: { resultsPerPage: 10 },
  alwaysSearchOnInitialLoad: true,
  trackUrlState: true
};

function raw(result, field, fallback = "") {
  // Elastic Search UI wraps returned values in { raw, snippet } objects.
  return result?.[field]?.raw ?? fallback;
}

function ResultCard({ result }) {
  // Normalize optional fields before rendering a stable card layout.
  const generatedText = raw(result, "generated_text", "(No transcription)");
  const filename = raw(result, "filename", "Unknown audio file");
  const duration = Number(raw(result, "duration", 0)).toFixed(1);
  const metadata = [
    raw(result, "age"),
    raw(result, "gender"),
    raw(result, "accent")
  ].filter(Boolean);

  return (
    <article className="result-card">
      <div className="result-card__heading">
        <h2>{filename}</h2>
        <span>{duration}s</span>
      </div>
      <p>{generatedText}</p>
      <div className="result-card__metadata">
        {metadata.length > 0
          ? metadata.map((value) => <span key={value}>{value}</span>)
          : <span>Demographic data unavailable</span>}
      </div>
    </article>
  );
}

function SearchResults() {
  // WithSearch selects only the state needed by this result presentation.
  return (
    <WithSearch
      mapContextToProps={({
        error,
        isLoading,
        pagingEnd,
        pagingStart,
        results,
        resultSearchTerm,
        totalPages,
        totalResults,
        wasSearched
      }) => ({
        error,
        isLoading,
        pagingEnd,
        pagingStart,
        results,
        resultSearchTerm,
        totalPages,
        totalResults,
        wasSearched
      })}
    >
      {({
        error,
        isLoading,
        pagingEnd,
        pagingStart,
        results,
        resultSearchTerm,
        totalPages,
        totalResults,
        wasSearched
      }) => {
        // Render mutually exclusive feedback states before normal results.
        if (error) {
          return (
            <div className="state-panel state-panel--error" role="alert">
              <h2>Search is temporarily unavailable</h2>
              <p>{error}</p>
            </div>
          );
        }

        if (isLoading) {
          return (
            <div className="state-panel" aria-live="polite">
              <div className="spinner" aria-hidden="true" />
              <p>Searching transcriptions...</p>
            </div>
          );
        }

        if (wasSearched && totalResults === 0) {
          return (
            <div className="state-panel">
              <h2>No transcriptions found</h2>
              <p>Try a broader phrase or remove one of the filters.</p>
            </div>
          );
        }

        return (
          <>
            <div className="results-summary" aria-live="polite">
              <strong>{totalResults.toLocaleString()} results</strong>
              {totalResults > 0 && (
                <span>
                  Showing {pagingStart}-{pagingEnd}
                  {resultSearchTerm ? ` for "${resultSearchTerm}"` : ""}
                </span>
              )}
            </div>

            <div className="results-list">
              {results.map((result) => (
                <ResultCard key={result.id.raw} result={result} />
              ))}
            </div>

            {totalPages > 1 && (
              <nav className="pagination" aria-label="Search result pages">
                <Paging />
              </nav>
            )}
          </>
        );
      }}
    </WithSearch>
  );
}

function Filters() {
  return (
    <aside className="filters" aria-label="Search filters">
      <div className="filters__heading">
        <h2>Filters</h2>
        <WithSearch mapContextToProps={({ clearFilters }) => ({ clearFilters })}>
          {({ clearFilters }) => (
            <button type="button" className="text-button" onClick={clearFilters}>
              Clear all
            </button>
          )}
        </WithSearch>
      </div>
      {/* Search UI generates facet controls from the server-owned config. */}
      <Facet field="duration" label="Duration" filterType="any" />
      <Facet field="age" label="Age" filterType="any" />
      <Facet field="gender" label="Gender" filterType="any" />
      <Facet field="accent" label="Accent" filterType="any" isFilterable />
    </aside>
  );
}

function App() {
  // ErrorBoundary prevents connector/render failures from blanking the page.
  return (
    <SearchProvider config={searchConfig}>
      <ErrorBoundary>
        <header className="site-header">
          <div>
            <p className="eyebrow">HTX AIE Technical Assessment</p>
            <h1>Common Voice Transcription Search</h1>
            <p>
              Search generated speech transcriptions and narrow results by
              duration or speaker metadata.
            </p>
          </div>
        </header>

        <main className="page-shell">
          <section className="search-panel" aria-label="Transcription search">
            {/* Submit explicitly instead of querying on every keystroke. */}
            <SearchBox
              searchAsYouType={false}
              shouldClearFilters={false}
              inputProps={{
                placeholder: "Search generated transcriptions...",
                "aria-label": "Search generated transcriptions"
              }}
            />
          </section>

          <div className="search-layout">
            <Filters />
            <section className="results" aria-label="Search results">
              <SearchResults />
            </section>
          </div>
        </main>
      </ErrorBoundary>
    </SearchProvider>
  );
}

// Mount the React application into the div supplied by index.html.
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
