"""Transcribe the Common Voice development set through the ASR HTTP API."""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path
from typing import Any

import requests

# Defaults are resolved relative to this file so the script works from any
# current working directory.
DEFAULT_API_URL = os.getenv("ASR_API_URL", "http://localhost:8001/asr")
DEFAULT_DATASET_DIR = Path(__file__).resolve().parent / "cv-valid-dev"
DEFAULT_CSV_PATH = DEFAULT_DATASET_DIR / "cv-valid-dev.csv"
GENERATED_TEXT_COLUMN = "generated_text"


class TranscriptionError(RuntimeError):
    """Raised when one audio file cannot be transcribed after all retries."""


def parse_args() -> argparse.Namespace:
    """Read command-line options for the batch transcription job."""
    # argparse provides validation, generated help text, and named attributes.
    parser = argparse.ArgumentParser(
        description=(
            "Call the ASR API for Common Voice MP3 files and write each "
            "transcription to the generated_text CSV column."
        )
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Input/output CSV path (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help=f"Directory containing MP3 files (default: {DEFAULT_DATASET_DIR})",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"ASR endpoint URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Atomically save the CSV after this many successful requests.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Process at most this many pending rows; useful for a smoke test.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum request attempts for each audio file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-request read timeout in seconds.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Transcribe rows that already contain generated_text.",
    )
    return parser.parse_args()


def load_csv(csv_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Load all CSV rows while preserving the original column order."""
    # Validate the source before attempting any API requests.
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"CSV file has no header: {csv_path}")
        if "filename" not in reader.fieldnames:
            raise ValueError("CSV file must contain a filename column.")

        fieldnames = list(reader.fieldnames)
        rows = [dict(row) for row in reader]

    # Older source CSVs do not contain the assessment's generated column.
    if GENERATED_TEXT_COLUMN not in fieldnames:
        fieldnames.append(GENERATED_TEXT_COLUMN)
        for row in rows:
            row[GENERATED_TEXT_COLUMN] = ""

    return rows, fieldnames


def resolve_audio_path(filename: str, audio_dir: Path) -> Path:
    """Map a CSV filename to its extracted MP3 without duplicating directories."""
    # The supplied CSV may store either a basename or a cv-valid-dev-prefixed
    # path, so try each valid layout without relying on string replacement.
    csv_path = Path(filename)
    candidates = [
        audio_dir / csv_path.name,
        audio_dir / csv_path,
        audio_dir.parent / csv_path,
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        f"Audio file '{filename}' was not found under {audio_dir}."
    )


def validate_api_response(payload: Any) -> tuple[str, str]:
    """Validate and extract the fields required from an ASR API response."""
    # Reject malformed responses immediately rather than writing partial rows.
    if not isinstance(payload, dict):
        raise ValueError("ASR API returned a non-object JSON response.")

    transcription = payload.get("transcription")
    duration = payload.get("duration")
    if not isinstance(transcription, str):
        raise ValueError("ASR API response is missing string transcription.")
    if not isinstance(duration, str):
        raise ValueError("ASR API response is missing string duration.")

    return transcription, duration


def transcribe_file(
    session: requests.Session,
    api_url: str,
    audio_path: Path,
    retries: int,
    timeout: float,
) -> tuple[str, str]:
    """Upload one MP3 and retry transient request failures with backoff."""
    last_error: Exception | None = None

    # Reopen the file for every attempt because requests consumes the stream.
    for attempt in range(1, retries + 1):
        try:
            with audio_path.open("rb") as audio_file:
                response = session.post(
                    api_url,
                    files={"file": (audio_path.name, audio_file, "audio/mpeg")},
                    timeout=(10, timeout),
                )
            response.raise_for_status()
            return validate_api_response(response.json())
        except (OSError, ValueError, requests.RequestException) as error:
            last_error = error
            if attempt < retries:
                # Exponential delays reduce immediate pressure on a recovering API.
                delay = 2 ** (attempt - 1)
                print(
                    f"  Attempt {attempt}/{retries} failed for "
                    f"{audio_path.name}; retrying in {delay}s: {error}"
                )
                time.sleep(delay)

    raise TranscriptionError(
        f"Failed to transcribe {audio_path.name} after {retries} attempts: "
        f"{last_error}"
    )


def save_csv_atomic(
    csv_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    """Write a complete checkpoint and atomically replace the previous CSV."""
    # A sibling temporary file prevents an interruption from leaving a
    # half-written CSV that cannot be resumed.
    temporary_path = csv_path.with_suffix(f"{csv_path.suffix}.tmp")

    with temporary_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    temporary_path.replace(csv_path)


def decode_dataset(
    csv_path: Path,
    audio_dir: Path,
    api_url: str,
    checkpoint_every: int,
    max_files: int | None,
    retries: int,
    timeout: float,
    overwrite: bool,
) -> tuple[int, list[str]]:
    """Transcribe pending CSV rows, checkpoint progress, and return failures."""
    # Fail on invalid controls before opening files or making HTTP requests.
    if checkpoint_every < 1:
        raise ValueError("--checkpoint-every must be at least 1.")
    if retries < 1:
        raise ValueError("--retries must be at least 1.")
    if max_files is not None and max_files < 1:
        raise ValueError("--max-files must be at least 1.")

    csv_path = csv_path.resolve()
    audio_dir = audio_dir.resolve()
    rows, fieldnames = load_csv(csv_path)

    # A valid duration marks an empty model transcription as complete. This
    # preserves genuine empty CTC output instead of retrying it forever.
    pending_indexes = [
        index
        for index, row in enumerate(rows)
        if overwrite
        or (
            not row.get(GENERATED_TEXT_COLUMN, "").strip()
            and not row.get("duration", "").strip()
        )
    ]
    if max_files is not None:
        pending_indexes = pending_indexes[:max_files]

    print(f"CSV rows: {len(rows)}")
    print(f"Pending rows selected: {len(pending_indexes)}")
    print(f"ASR endpoint: {api_url}")

    processed = 0
    successes_since_checkpoint = 0
    failures: list[str] = []

    try:
        # One Session reuses TCP connections across thousands of uploads.
        with requests.Session() as session:
            for position, row_index in enumerate(pending_indexes, start=1):
                row = rows[row_index]
                filename = row["filename"]

                try:
                    audio_path = resolve_audio_path(filename, audio_dir)
                    transcription, duration = transcribe_file(
                        session=session,
                        api_url=api_url,
                        audio_path=audio_path,
                        retries=retries,
                        timeout=timeout,
                    )
                    row[GENERATED_TEXT_COLUMN] = transcription
                    row["duration"] = duration
                    processed += 1
                    successes_since_checkpoint += 1
                    print(
                        f"[{position}/{len(pending_indexes)}] "
                        f"{audio_path.name}: {transcription}"
                    )
                except (FileNotFoundError, TranscriptionError) as error:
                    failures.append(f"{filename}: {error}")
                    print(f"[{position}/{len(pending_indexes)}] ERROR: {error}")

                # Persist progress regularly so a long run can resume safely.
                if successes_since_checkpoint >= checkpoint_every:
                    save_csv_atomic(csv_path, rows, fieldnames)
                    successes_since_checkpoint = 0
                    print(f"Checkpoint saved after {processed} transcriptions.")
    finally:
        # Preserve the latest successful rows even if the process is interrupted.
        save_csv_atomic(csv_path, rows, fieldnames)

    return processed, failures


def main() -> int:
    """Run the batch decoder and return a process exit code."""
    args = parse_args()

    try:
        processed, failures = decode_dataset(
            csv_path=args.csv,
            audio_dir=args.audio_dir,
            api_url=args.api_url,
            checkpoint_every=args.checkpoint_every,
            max_files=args.max_files,
            retries=args.retries,
            timeout=args.timeout,
            overwrite=args.overwrite,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"Configuration error: {error}")
        return 2

    print(f"Completed transcriptions this run: {processed}")
    print(f"Failed rows this run: {len(failures)}")
    for failure in failures:
        print(f"  - {failure}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
