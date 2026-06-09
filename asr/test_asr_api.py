"""Tests for the ASR HTTP API."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import asr_api
from asr_api import SAMPLE_RATE, app


client = TestClient(app)


class FakeASRService:
    def transcribe(self, audio: np.ndarray) -> str:
        assert audio.size == SAMPLE_RATE * 2
        return "TEST TRANSCRIPTION"


def test_ping_returns_pong() -> None:
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_asr_returns_transcription_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_path: Path | None = None

    def fake_decode_audio(file_path: Path) -> tuple[np.ndarray, float]:
        nonlocal temporary_path
        temporary_path = file_path
        assert file_path.exists()
        assert file_path.read_bytes() == b"fake mp3 content"
        return np.zeros(SAMPLE_RATE * 2, dtype=np.float32), 2.0

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
    response = client.post(
        "/asr",
        files={"file": ("sample.wav", b"audio content", "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only MP3 files are supported."}


def test_asr_deletes_temporary_file_when_decoding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_path: Path | None = None

    def failing_decode(file_path: Path) -> tuple[np.ndarray, float]:
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
