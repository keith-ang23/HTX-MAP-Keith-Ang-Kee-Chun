"""Create the Common Voice Elasticsearch index and bulk-index its CSV rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from elasticsearch import Elasticsearch, helpers

DEFAULT_ELASTICSEARCH_URL = os.getenv(
    "ELASTICSEARCH_URL",
    "http://localhost:9200",
)
DEFAULT_INDEX_NAME = os.getenv("ELASTICSEARCH_INDEX", "cv-transcriptions")
DEFAULT_CSV_PATH = Path(__file__).resolve().parent / "cv-valid-dev.csv"

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

INDEX_DEFINITION: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "filename": {"type": "keyword"},
            "text": {"type": "text"},
            "up_votes": {"type": "integer"},
            "down_votes": {"type": "integer"},
            "age": {"type": "keyword"},
            "gender": {"type": "keyword"},
            "accent": {"type": "keyword"},
            "duration": {"type": "float"},
            "generated_text": {"type": "text"},
        },
    },
}


def parse_args() -> argparse.Namespace:
    """Read command-line options for connecting and indexing."""
    parser = argparse.ArgumentParser(
        description="Bulk-index Common Voice transcriptions into Elasticsearch."
    )
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
    return parser.parse_args()


def optional_string(value: str | None) -> str | None:
    """Convert a blank CSV value to null so it is not indexed as a filter value."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_integer(value: str | None, column: str, row_number: int) -> int:
    """Parse a required integer and report the source row on invalid input."""
    try:
        return int(value or 0)
    except ValueError as error:
        raise ValueError(
            f"Invalid integer in column '{column}' at CSV row {row_number}: "
            f"{value!r}"
        ) from error


def parse_duration(value: str | None, row_number: int) -> float:
    """Parse and validate the positive duration required for every document."""
    try:
        duration = float(value or "")
    except ValueError as error:
        raise ValueError(
            f"Invalid duration at CSV row {row_number}: {value!r}"
        ) from error

    if duration <= 0:
        raise ValueError(
            f"Duration must be positive at CSV row {row_number}: {duration}"
        )
    return duration


def deterministic_document_id(filename: str) -> str:
    """Return a stable ID so repeated indexing cannot create duplicates."""
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()


def build_document(row: dict[str, str], row_number: int) -> dict[str, Any]:
    """Convert one CSV row into values matching the explicit index mapping."""
    filename = (row.get("filename") or "").strip()
    if not filename:
        raise ValueError(f"Missing filename at CSV row {row_number}.")

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
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    documents: list[dict[str, Any]] = []
    seen_filenames: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no header: {csv_path}")

        missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV file is missing required columns: {missing}")

        for row_number, row in enumerate(reader, start=2):
            document = build_document(dict(row), row_number)
            filename = document["filename"]
            if filename in seen_filenames:
                raise ValueError(
                    f"Duplicate filename at CSV row {row_number}: {filename}"
                )
            seen_filenames.add(filename)
            documents.append(document)

    if not documents:
        raise ValueError(f"CSV file contains no data rows: {csv_path}")

    return documents


def create_index(
    client: Elasticsearch,
    index_name: str,
    recreate: bool,
) -> None:
    """Create the mapped index, optionally deleting an existing copy first."""
    exists = client.indices.exists(index=index_name)
    if exists and recreate:
        client.indices.delete(index=index_name)
        exists = False

    if not exists:
        client.indices.create(index=index_name, **INDEX_DEFINITION)


def bulk_actions(
    documents: list[dict[str, Any]],
    index_name: str,
) -> Iterator[dict[str, Any]]:
    """Yield deterministic Elasticsearch bulk-index actions."""
    for document in documents:
        yield {
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
    if chunk_size < 1:
        raise ValueError("--chunk-size must be at least 1.")

    indexed = 0
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

    client.indices.refresh(index=index_name)
    return indexed


def main() -> int:
    """Connect to Elasticsearch, create the index, and load the CSV."""
    args = parse_args()

    try:
        documents = load_documents(args.csv.resolve())
        client = Elasticsearch(args.url, request_timeout=60)
        if not client.ping():
            raise ConnectionError(f"Elasticsearch is unavailable at {args.url}")

        health = client.cluster.health(
            wait_for_status="yellow",
            timeout="60s",
        )
        print(
            f"Connected to cluster '{health['cluster_name']}' "
            f"with status {health['status']}."
        )

        create_index(
            client=client,
            index_name=args.index,
            recreate=not args.no_recreate,
        )
        indexed = index_documents(
            client=client,
            index_name=args.index,
            documents=documents,
            chunk_size=args.chunk_size,
        )
        count = client.count(index=args.index)["count"]
    except (
        ConnectionError,
        FileNotFoundError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"Indexing failed: {error}")
        return 1
    except Exception as error:
        print(f"Elasticsearch operation failed: {error}")
        return 1

    print(f"Indexed documents this run: {indexed}")
    print(f"Documents in '{args.index}': {count}")
    if count != len(documents):
        print(
            f"Index count mismatch: expected {len(documents)}, found {count}."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
