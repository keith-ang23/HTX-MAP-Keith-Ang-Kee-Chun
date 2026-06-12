"""Tests for the ASR HTTP API."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import asr_api
from asr_api import SAMPLE_RATE, app


client = TestClient(app)


class FakeASRService:
    """Replace the large Wav2Vec2 model with deterministic test inference."""

    def transcribe(self, audio: np.ndarray) -> str:
        # Confirm the endpoint forwards the decoded two-second waveform.
        assert audio.size == SAMPLE_RATE * 2
        return "TEST TRANSCRIPTION"


def test_ping_returns_pong() -> None:
    """The lightweight health endpoint should not require model inference."""
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_asr_returns_transcription_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid MP3 should return JSON and remove its temporary upload."""
    temporary_path: Path | None = None

    def fake_decode_audio(file_path: Path) -> tuple[np.ndarray, float]:
        """Inspect the saved upload and return predictable decoded audio."""
        nonlocal temporary_path
        temporary_path = file_path
        assert file_path.exists()
        assert file_path.read_bytes() == b"fake mp3 content"
        return np.zeros(SAMPLE_RATE * 2, dtype=np.float32), 2.0

    # Avoid real MP3 decoding and model inference in this HTTP contract test.
    monkeypatch.setattr(asr_api, "decode_audio", fake_decode_audio)
    app.state.asr_service = FakeASRService()

    response = client.post(
        "/asr",
        files={"file": ("sample.mp3", b"fake mp3 content", "audio/mpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "transcription": "TEST TRANSCRIPTION",
        "duration": "2.0",
    }
    assert temporary_path is not None
    assert not temporary_path.exists()


def test_asr_rejects_non_mp3_upload() -> None:
    """The assessment endpoint accepts MP3 files only."""
    response = client.post(
        "/asr",
        files={"file": ("sample.wav", b"audio content", "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only MP3 files are supported."}


def test_asr_deletes_temporary_file_when_decoding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finally block must delete uploads even when decoding raises."""
    temporary_path: Path | None = None

    def failing_decode(file_path: Path) -> tuple[np.ndarray, float]:
        """Record the temporary path before simulating an invalid audio file."""
        nonlocal temporary_path
        temporary_path = file_path
        raise ValueError("Invalid audio")

    monkeypatch.setattr(asr_api, "decode_audio", failing_decode)
    app.state.asr_service = FakeASRService()

    response = client.post(
        "/asr",
        files={"file": ("broken.mp3", b"not an mp3", "audio/mpeg")},
    )

    assert response.status_code == 422
    assert temporary_path is not None
    assert not temporary_path.exists()
