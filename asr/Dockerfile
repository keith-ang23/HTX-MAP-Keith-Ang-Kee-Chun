FROM python:3.11-slim

# Prevent Python from buffering logs and writing bytecode inside the container.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ASR_MODEL_CACHE_DIR=/app/model_cache

WORKDIR /app

# FFmpeg provides reliable MP3 decoding support for librosa/audioread.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies before copying source code so Docker can cache this layer.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        torch==2.7.1 \
        --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r /app/requirements.txt

COPY asr/asr_api.py /app/asr_api.py

# Run as an unprivileged user while retaining write access to the model cache.
RUN useradd --create-home --uid 10001 asr \
    && mkdir -p /app/model_cache \
    && chown -R asr:asr /app

USER asr

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD curl --fail --silent http://localhost:8001/ping > /dev/null || exit 1

CMD ["uvicorn", "asr_api:app", "--host", "0.0.0.0", "--port", "8001"]
