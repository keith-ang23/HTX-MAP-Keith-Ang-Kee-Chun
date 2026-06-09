"""Serve health-check and speech-to-text endpoints for the ASR service."""

# Postpone evaluation of type hints so modern annotations can be used safely.
from __future__ import annotations

# Standard-library tools for logging, configuration, and temporary files.
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

# Third-party libraries for audio decoding, numerical arrays, and inference.
import librosa
import numpy as np
import torch
# FastAPI classes used to define the application, uploads, and HTTP errors.
from fastapi import FastAPI, File, HTTPException, UploadFile
# Pydantic validates and documents the JSON response returned by the API.
from pydantic import BaseModel
# Hugging Face classes load the audio processor and Wav2Vec2 CTC model.
from transformers import AutoModelForCTC, AutoProcessor

# Create a module-specific logger so startup and inference failures are recorded.
LOGGER = logging.getLogger(__name__)

# Permit deployment environments to override the model without changing code.
MODEL_ID = os.getenv("ASR_MODEL_ID", "facebook/wav2vec2-large-960h")

# Store downloaded model files locally so later startups can reuse them.
MODEL_CACHE_DIR = os.getenv("ASR_MODEL_CACHE_DIR", "model_cache")

# The selected Wav2Vec2 model expects mono audio sampled at 16 kHz.
SAMPLE_RATE = 16_000

# Copy uploads in 1 MiB pieces instead of loading the entire MP3 into memory.
UPLOAD_CHUNK_SIZE = 1024 * 1024


class ASRResponse(BaseModel):
    """Define and validate the JSON returned after a successful request."""

    # Text produced by the Wav2Vec2 model.
    transcription: str

    # Audio duration formatted as a string, as required by the assessment.
    duration: str


class ASRService:
    """Own the Wav2Vec2 components and provide reusable inference logic."""

    def __init__(self, model_id: str, cache_dir: str) -> None:
        """Download or load the processor and model once during API startup."""
        # Model loading is slow, so log when it starts and finishes.
        LOGGER.info("Loading ASR model %s", model_id)

        # The processor normalizes audio and converts predicted token IDs to text.
        self.processor = AutoProcessor.from_pretrained(
            model_id,
            cache_dir=cache_dir,
        )

        # AutoModelForCTC selects the correct Wav2Vec2 transcription model class.
        self.model = AutoModelForCTC.from_pretrained(
            model_id,
            cache_dir=cache_dir,
        )

        # Evaluation mode disables training-only behavior such as dropout.
        self.model.eval()
        LOGGER.info("ASR model loaded")

    def transcribe(self, audio: np.ndarray) -> str:
        """Convert a mono 16 kHz NumPy waveform into transcribed text."""
        # Convert raw samples into the tensor format expected by Wav2Vec2.
        inputs = self.processor(
            audio,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
            padding=True,
        )

        # Disable gradient tracking because this service performs inference only.
        # This reduces both memory usage and processing overhead.
        with torch.inference_mode():
            # Logits contain a score for every vocabulary token at each time step.
            logits = self.model(**inputs).logits

        # Select the highest-scoring token at every time step.
        predicted_ids = torch.argmax(logits, dim=-1)

        # Collapse CTC tokens and convert the first result into readable text.
        return self.processor.batch_decode(predicted_ids)[0]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage resources that live for the full lifetime of the API process."""
    # Loading here creates one shared model instead of reloading it per request.
    application.state.asr_service = ASRService(MODEL_ID, MODEL_CACHE_DIR)

    # Yield control to FastAPI so it can begin accepting HTTP requests.
    yield

    # Drop the reference during shutdown so Python can release model memory.
    application.state.asr_service = None


# Create the FastAPI application and register the startup/shutdown lifecycle.
app = FastAPI(
    title="HTX ASR API",
    description="API for health checks and audio transcription.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/ping")
def ping() -> dict[str, str]:
    """Return a lightweight health-check response without running inference."""
    return {"message": "pong"}


def decode_audio(file_path: Path) -> tuple[np.ndarray, float]:
    """Decode an MP3 into mono 16 kHz samples and return its duration."""
    # librosa decodes the MP3, mixes channels to mono, and resamples to 16 kHz.
    # The original sample rate is ignored because the returned audio is 16 kHz.
    audio, _ = librosa.load(file_path, sr=SAMPLE_RATE, mono=True)

    # Reject files that decode successfully but contain no audio samples.
    if audio.size == 0:
        raise ValueError("The uploaded audio file is empty.")

    # Duration in seconds equals the sample count divided by samples per second.
    duration = audio.size / SAMPLE_RATE
    return audio, duration


async def save_upload(upload: UploadFile, destination: Path) -> None:
    """Copy an uploaded file to disk in bounded chunks."""
    # Open the temporary destination in binary-write mode.
    with destination.open("wb") as output:
        # UploadFile.read is asynchronous, so it does not block other API work
        # while FastAPI reads each chunk from the incoming multipart request.
        while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
            output.write(chunk)


@app.post("/asr", response_model=ASRResponse)
async def transcribe_audio(file: UploadFile = File(...)) -> ASRResponse:
    """Accept an MP3 upload, transcribe it, and return text plus duration."""
    # FastAPI maps the required multipart/form-data field named "file" here.
    # Some clients may omit a filename, so fall back to an empty string.
    filename = file.filename or ""

    # The assessment specifically requires an MP3 input file.
    if Path(filename).suffix.lower() != ".mp3":
        raise HTTPException(status_code=400, detail="Only MP3 files are supported.")

    # Keep the path outside the try block so the finally block can always see it.
    temporary_path: Path | None = None
    try:
        # delete=False keeps the file available after this context manager closes.
        # This is necessary because the audio decoder opens the path separately.
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temporary:
            temporary_path = Path(temporary.name)

        # Persist the multipart upload before passing its path to librosa.
        await save_upload(file, temporary_path)

        # Decode and normalize the audio before model inference.
        audio, duration = decode_audio(temporary_path)

        # Retrieve the single model instance created by the lifespan function.
        service: ASRService = app.state.asr_service

        # Run Wav2Vec2 inference on the normalized waveform.
        transcription = service.transcribe(audio)

        # Format duration to one decimal place and serialize through Pydantic.
        return ASRResponse(
            transcription=transcription,
            duration=f"{duration:.1f}",
        )
    except HTTPException:
        # Preserve intentional HTTP errors and their original status codes.
        raise
    except Exception as error:
        # Record the full traceback internally without exposing details to clients.
        LOGGER.exception("ASR transcription failed")

        # Convert decoding and inference errors into a controlled API response.
        raise HTTPException(
            status_code=422,
            detail="The uploaded MP3 file could not be transcribed.",
        ) from error
    finally:
        # Close FastAPI's upload handle whether the request succeeds or fails.
        await file.close()

        # Always remove the uploaded file; missing_ok also makes cleanup idempotent.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
