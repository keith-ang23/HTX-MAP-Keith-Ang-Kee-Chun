"""Tests for the Common Voice Elasticsearch indexer."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load_indexer_module() -> ModuleType:
    module_path = Path(__file__).with_name("cv-index.py")
    spec = importlib.util.spec_from_file_location("cv_index", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cv_index = load_indexer_module()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "filename",
                "text",
                "up_votes",
                "down_votes",
                "age",
                "gender",
                "accent",
                "duration",
                "generated_text",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def valid_row() -> dict[str, str]:
    return {
        "filename": "cv-valid-dev/sample-000000.mp3",
        "text": "reference text",
        "up_votes": "2",
        "down_votes": "0",
        "age": "twenties",
        "gender": "female",
        "accent": "us",
        "duration": "5.1",
        "generated_text": "GENERATED TEXT",
    }


def test_load_documents_converts_mapped_types(tmp_path: Path) -> None:
    csv_path = tmp_path / "cv-valid-dev.csv"
    write_csv(csv_path, [valid_row()])

    documents = cv_index.load_documents(csv_path)

    assert documents == [
        {
            "filename": "cv-valid-dev/sample-000000.mp3",
            "text": "reference text",
            "up_votes": 2,
            "down_votes": 0,
            "age": "twenties",
            "gender": "female",
            "accent": "us",
            "duration": 5.1,
            "generated_text": "GENERATED TEXT",
        }
    ]


def test_blank_filter_values_become_null(tmp_path: Path) -> None:
    row = valid_row()
    row.update({"age": "", "gender": " ", "accent": ""})
    csv_path = tmp_path / "cv-valid-dev.csv"
    write_csv(csv_path, [row])

    document = cv_index.load_documents(csv_path)[0]

    assert document["age"] is None
    assert document["gender"] is None
    assert document["accent"] is None


def test_document_id_is_stable_and_filename_specific() -> None:
    first = cv_index.deterministic_document_id("sample-000001.mp3")
    repeat = cv_index.deterministic_document_id("sample-000001.mp3")
    second = cv_index.deterministic_document_id("sample-000002.mp3")

    assert first == repeat
    assert first != second
    assert len(first) == 64


def test_duplicate_filename_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "cv-valid-dev.csv"
    row = valid_row()
    write_csv(csv_path, [row, row])

    with pytest.raises(ValueError, match="Duplicate filename"):
        cv_index.load_documents(csv_path)


def test_mapping_uses_required_search_and_filter_types() -> None:
    properties = cv_index.INDEX_DEFINITION["mappings"]["properties"]

    assert properties["generated_text"]["type"] == "text"
    assert properties["duration"]["type"] == "float"
    assert properties["age"]["type"] == "keyword"
    assert properties["gender"]["type"] == "keyword"
    assert properties["accent"]["type"] == "keyword"
