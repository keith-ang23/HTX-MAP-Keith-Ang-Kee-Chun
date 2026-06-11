"""Create the Common Voice Elasticsearch index and bulk-index its CSV rows."""

# Delay evaluation of type annotations for compatibility and cleaner hints.
from __future__ import annotations

# Standard-library modules for CLI parsing, CSV reading, IDs, and file paths.
import argparse
import csv
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Elasticsearch is the client; helpers provides efficient bulk operations.
from elasticsearch import Elasticsearch, helpers

# Environment variables allow deployment settings to override local defaults.
DEFAULT_ELASTICSEARCH_URL = os.getenv(
    "ELASTICSEARCH_URL",
    "http://localhost:9200",
)
DEFAULT_INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "cv-transcriptions")

# Resolve the default CSV relative to this script, not the current terminal path.
DEFAULT_CSV_PATH = Path(__file__).resolve().parent / "cv-valid-dev.csv"

# Refuse to index a CSV that cannot satisfy the assessment's search fields.
REQUIRED_COLUMNS = {
    "filename",
    "text",
    "up_votes",
    "down_votes",
    "age",
    "gender",
    "accent",
    "duration",
    "generated_text",
}

# Define index settings and field types before documents are inserted.
INDEX_DEFINITION: dict[str, Any] = {
    "settings": {
        # One primary shard is sufficient for this small 4,076-document dataset.
        "number_of_shards": 1,

        # One replica places a second copy on the other Elasticsearch node.
        "number_of_replicas": 1,
    },
    "mappings": {
        # Reject unexpected fields instead of silently creating accidental types.
        "dynamic": "strict",
        "properties": {
            # Keyword fields support exact matching, filtering, and aggregation.
            "filename": {"type": "keyword"},

            # Text fields are analyzed into searchable words.
            "text": {"type": "text"},

            # Vote counts are stored numerically rather than as CSV strings.
            "up_votes": {"type": "integer"},
            "down_votes": {"type": "integer"},

            # Demographic fields are exact filter values for Search UI facets.
            "age": {"type": "keyword"},
            "gender": {"type": "keyword"},
            "accent": {"type": "keyword"},

            # Float permits numeric range filters such as 5.0 to 6.0 seconds.
            "duration": {"type": "float"},

            # generated_text is the main full-text field produced by the ASR model.
            "generated_text": {"type": "text"},
        },
    },
}


def parse_args() -> argparse.Namespace:
    """Read command-line options for connecting and indexing."""
    # argparse generates --help output and validates basic argument types.
    parser = argparse.ArgumentParser(
        description="Bulk-index Common Voice transcriptions into Elasticsearch."
    )

    # Each option has a practical local default but remains configurable.
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"CSV file to index (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_ELASTICSEARCH_URL,
        help=f"Elasticsearch URL (default: {DEFAULT_ELASTICSEARCH_URL})",
    )
    parser.add_argument(
        "--index",
        default=DEFAULT_INDEX_NAME,
        help=f"Index name (default: {DEFAULT_INDEX_NAME})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Documents sent in each bulk request (default: 500)",
    )
    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Keep the existing index and upsert deterministic document IDs.",
    )

    # Convert command-line text into attributes such as args.csv and args.url.
    return parser.parse_args()


def optional_string(value: str | None) -> str | None:
    """Convert a blank CSV value to null so it is not indexed as a filter value."""
    # DictReader may return None when a column value is absent.
    if value is None:
        return None

    # Whitespace-only values should not appear as empty facet choices.
    stripped = value.strip()
    return stripped or None


def parse_integer(value: str | None, column: str, row_number: int) -> int:
    """Parse a required integer and report the source row on invalid input."""
    try:
        # Empty vote values are treated as zero.
        return int(value or 0)
    except ValueError as error:
        # Include the column and row so malformed source data is easy to locate.
        raise ValueError(
            f"Invalid integer in column '{column}' at CSV row {row_number}: "
            f"{value!r}"
        ) from error


def parse_duration(value: str | None, row_number: int) -> float:
    """Parse and validate the positive duration required for every document."""
    try:
        # Convert the CSV string into the float required by the mapping.
        duration = float(value or "")
    except ValueError as error:
        raise ValueError(
            f"Invalid duration at CSV row {row_number}: {value!r}"
        ) from error

    # Zero and negative durations indicate invalid audio metadata.
    if duration <= 0:
        raise ValueError(
            f"Duration must be positive at CSV row {row_number}: {duration}"
        )
    return duration


def deterministic_document_id(filename: str) -> str:
    """Return a stable ID so repeated indexing cannot create duplicates."""
    # The same filename always produces the same 64-character SHA-256 ID.
    # Elasticsearch's index operation then replaces that document on a rerun.
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def build_document(row: dict[str, str], row_number: int) -> dict[str, Any]:
    """Convert one CSV row into values matching the explicit index mapping."""
    # Filename is the source record's stable identity and therefore required.
    filename = (row.get("filename") or "").strip()
    if not filename:
        raise ValueError(f"Missing filename at CSV row {row_number}.")

    # Convert every CSV string into the type declared in INDEX_DEFINITION.
    return {
        "filename": filename,
        "text": (row.get("text") or "").strip(),
        "up_votes": parse_integer(row.get("up_votes"), "up_votes", row_number),
        "down_votes": parse_integer(
            row.get("down_votes"),
            "down_votes",
            row_number,
        ),
        "age": optional_string(row.get("age")),
        "gender": optional_string(row.get("gender")),
        "accent": optional_string(row.get("accent")),
        "duration": parse_duration(row.get("duration"), row_number),
        "generated_text": (row.get("generated_text") or "").strip(),
    }


def load_documents(csv_path: Path) -> list[dict[str, Any]]:
    """Load, validate, and convert every CSV row before modifying the index."""
    # Fail before contacting Elasticsearch if the source file is unavailable.
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    documents: list[dict[str, Any]] = []

    # Track filenames so duplicate source rows cannot overwrite each other.
    seen_filenames: set[str] = set()

    # utf-8-sig accepts both normal UTF-8 and files containing a UTF-8 BOM.
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)

        # DictReader needs a header to map each value to a field name.
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no header: {csv_path}")

        # Check all required fields once before converting thousands of rows.
        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV file is missing required columns: {missing}")

        # Start at 2 because row 1 contains the CSV header.
        for row_number, row in enumerate(reader, start=2):
            document = build_document(dict(row), row_number)
            filename = document["filename"]

            # Deterministic IDs rely on filenames being unique in the source CSV.
            if filename in seen_filenames:
                raise ValueError(
                    f"Duplicate filename at CSV row {row_number}: {filename}"
                )
            seen_filenames.add(filename)
            documents.append(document)

    # An empty but structurally valid CSV should not create an empty index.
    if not documents:
        raise ValueError(f"CSV file contains no data rows: {csv_path}")

    return documents


def create_index(
    client: Elasticsearch,
    index_name: str,
    recreate: bool,
) -> None:
    """Create the mapped index, optionally deleting an existing copy first."""
    # Ask Elasticsearch whether the target index already exists.
    exists = client.indices.exists(index=index_name)

    # Default behavior gives a clean, repeatable index with known mappings.
    if exists and recreate:
        client.indices.delete(index=index_name)
        exists = False

    # In --no-recreate mode, retain an existing index and its documents.
    if not exists:
        client.indices.create(index=index_name, **INDEX_DEFINITION)


def bulk_actions(
    documents: list[dict[str, Any]],
    index_name: str,
) -> Iterator[dict[str, Any]]:
    """Yield deterministic Elasticsearch bulk-index actions."""
    for document in documents:
        # helpers.streaming_bulk consumes actions one at a time, avoiding a
        # second large in-memory request body.
        yield {
            # "index" creates the document or replaces an existing matching ID.
            "_op_type": "index",
            "_index": index_name,
            "_id": deterministic_document_id(document["filename"]),
            "_source": document,
        }


def index_documents(
    client: Elasticsearch,
    index_name: str,
    documents: list[dict[str, Any]],
    chunk_size: int,
) -> int:
    """Bulk-index documents and raise immediately if any action fails."""
    # Prevent invalid chunk sizes from reaching the Elasticsearch helper.
    if chunk_size < 1:
        raise ValueError("--chunk-size must be at least 1.")

    indexed = 0

    # Split the documents into manageable bulk HTTP requests. The helper yields
    # one success/result pair for every action acknowledged by Elasticsearch.
    for success, result in helpers.streaming_bulk(
        client,
        bulk_actions(documents, index_name),
        chunk_size=chunk_size,
        raise_on_error=True,
        raise_on_exception=True,
    ):
        if not success:
            raise RuntimeError(f"Bulk indexing failed: {result}")
        indexed += 1

    # Refresh makes all newly indexed documents immediately searchable.
    client.indices.refresh(index=index_name)
    return indexed


def main() -> int:
    """Connect to Elasticsearch, create the index, and load the CSV."""
    args = parse_args()

    try:
        # Validate the complete CSV before deleting or modifying any index.
        documents = load_documents(args.csv.resolve())

        # request_timeout allows enough time for cluster and bulk operations.
        client = Elasticsearch(args.url, request_timeout=60)

        # ping performs a lightweight availability check.
        if not client.ping():
            raise ConnectionError(f"Elasticsearch is unavailable at {args.url}")

        # Yellow means all primary shards are assigned. The expected two-node
        # state is green because the replica can also be assigned.
        health = client.cluster.health(
            wait_for_status="yellow",
            timeout="60s",
        )
        print(
            f"Connected to cluster '{health['cluster_name']}' "
            f"with status {health['status']}."
        )

        # Recreate by default; --no-recreate switches to deterministic upserts.
        create_index(
            client=client,
            index_name=args.index,
            recreate=not args.no_recreate,
        )

        # Send every validated document through Elasticsearch's bulk API.
        indexed = index_documents(
            client=client,
            index_name=args.index,
            documents=documents,
            chunk_size=args.chunk_size,
        )

        # Count after refresh to verify the externally visible index result.
        count = client.count(index=args.index)["count"]
    except (
        ConnectionError,
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as error:
        # Known configuration and data errors produce a concise message.
        print(f"Indexing failed: {error}")
        return 1
    except Exception as error:
        # Catch Elasticsearch transport/API failures without hiding a bad exit.
        print(f"Elasticsearch operation failed: {error}")
        return 1

    print(f"Indexed documents this run: {indexed}")
    print(f"Documents in '{args.index}': {count}")

    # A successful bulk request should leave exactly one document per CSV row.
    if count != len(documents):
        print(
            f"Index count mismatch: expected {len(documents)}, found {count}."
        )
        return 1

    return 0


if __name__ == "__main__":
    # Convert main's return value into the shell process exit status.
    raise SystemExit(main())
