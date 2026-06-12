"""Tests for the Common Voice batch decoder."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def load_decoder_module() -> ModuleType:
    """Import the hyphenated script by path so its functions can be tested."""
    module_path = Path(__file__).with_name("cv-decode.py")
    spec = importlib.util.spec_from_file_location("cv_decode", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cv_decode = load_decoder_module()


def write_test_csv(csv_path: Path) -> None:
    """Create the smallest source CSV accepted by the batch decoder."""
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["filename", "text", "duration"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "filename": "cv-valid-dev/sample-000000.mp3",
                "text": "reference text",
                "duration": "",
            }
        )


def test_decode_dataset_adds_generated_text_and_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending row should receive both API fields and be saved to disk."""
    audio_dir = tmp_path / "cv-valid-dev"
    audio_dir.mkdir()
    (audio_dir / "sample-000000.mp3").write_bytes(b"audio")
    csv_path = audio_dir / "cv-valid-dev.csv"
    write_test_csv(csv_path)

    # Replace the HTTP upload with a deterministic response.
    monkeypatch.setattr(
        cv_decode,
        "transcribe_file",
        lambda **kwargs: ("GENERATED TRANSCRIPTION", "2.5"),
    )

    processed, failures = cv_decode.decode_dataset(
        csv_path=csv_path,
        audio_dir=audio_dir,
        api_url="http://localhost:8001/asr",
        checkpoint_every=1,
        max_files=None,
        retries=1,
        timeout=1,
        overwrite=False,
    )

    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert processed == 1
    assert failures == []
    assert rows[0]["generated_text"] == "GENERATED TRANSCRIPTION"
    assert rows[0]["duration"] == "2.5"


def test_decode_dataset_resumes_completed_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows with generated text should be skipped on a resumed run."""
    audio_dir = tmp_path / "cv-valid-dev"
    audio_dir.mkdir()
    csv_path = audio_dir / "cv-valid-dev.csv"
    write_test_csv(csv_path)

    rows, fieldnames = cv_decode.load_csv(csv_path)
    rows[0]["generated_text"] = "ALREADY COMPLETE"
    cv_decode.save_csv_atomic(csv_path, rows, fieldnames)

    def unexpected_call(**kwargs: object) -> tuple[str, str]:
        """Fail the test if resume logic contacts the API unnecessarily."""
        raise AssertionError("Completed rows must not call the API.")

    monkeypatch.setattr(cv_decode, "transcribe_file", unexpected_call)

    processed, failures = cv_decode.decode_dataset(
        csv_path=csv_path,
        audio_dir=audio_dir,
        api_url="http://localhost:8001/asr",
        checkpoint_every=1,
        max_files=None,
        retries=1,
        timeout=1,
        overwrite=False,
    )

    assert processed == 0
    assert failures == []


def test_decode_dataset_treats_empty_model_output_as_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duration proves that an empty CTC transcription was already processed."""
    audio_dir = tmp_path / "cv-valid-dev"
    audio_dir.mkdir()
    csv_path = audio_dir / "cv-valid-dev.csv"
    write_test_csv(csv_path)

    rows, fieldnames = cv_decode.load_csv(csv_path)
    rows[0]["generated_text"] = ""
    rows[0]["duration"] = "3.9"
    cv_decode.save_csv_atomic(csv_path, rows, fieldnames)

    def unexpected_call(**kwargs: object) -> tuple[str, str]:
        """Fail if a valid empty model output is incorrectly retried."""
        raise AssertionError("A completed empty model result must not be retried.")

    monkeypatch.setattr(cv_decode, "transcribe_file", unexpected_call)

    processed, failures = cv_decode.decode_dataset(
        csv_path=csv_path,
        audio_dir=audio_dir,
        api_url="http://localhost:8001/asr",
        checkpoint_every=1,
        max_files=None,
        retries=1,
        timeout=1,
        overwrite=False,
    )

    assert processed == 0
    assert failures == []


def test_resolve_audio_path_handles_csv_directory_prefix(tmp_path: Path) -> None:
    """CSV paths prefixed with cv-valid-dev should resolve without duplication."""
    audio_dir = tmp_path / "cv-valid-dev"
    audio_dir.mkdir()
    expected = audio_dir / "sample-000000.mp3"
    expected.write_bytes(b"audio")

    result = cv_decode.resolve_audio_path(
        "cv-valid-dev/sample-000000.mp3",
        audio_dir,
    )

    assert result == expected.resolve()
