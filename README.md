# HTX xData AIE Technical Assessment

This repository contains an Automatic Speech Recognition (ASR) service,
Common Voice transcription workflow, Elasticsearch backend, Search UI, and
AWS deployment design for the HTX xData technical assessment.

## Current status

Repository and Python environment setup are complete. The ASR service
provides health-check and Wav2Vec2 transcription endpoints.

## Prerequisites

- Git
- Python 3.11
- Docker Desktop with Docker Compose
- Node.js 24 or another supported LTS release
- At least 8 GB of memory allocated to Docker

The development environment used for this submission is Windows with Git
Bash, WSL 2, Python 3.11.15, and Docker Desktop.

## Python setup

From the repository root, create a Python 3.11 virtual environment:

```bash
python3.11 -m venv .venv
```

Activate the environment in Git Bash:

```bash
source .venv/Scripts/activate
```

Install the Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Confirm that the environment uses Python 3.11:

```bash
python --version
python -c "import sys; print(sys.executable)"
```

## Project structure

```text
.
|-- asr/                 # ASR API, batch decoder, and container definition
|-- deployment-design/   # AWS architecture source and exported PDF
|-- elastic-backend/     # Two-node Elasticsearch cluster and indexing script
|-- search-ui/           # Search frontend and container definition
|-- requirements.txt     # Pinned Python dependencies
`-- README.md
```

Directories beyond `asr/` will be added as their assessment tasks are
implemented.

## ASR API

Start the API from the repository root:

```bash
uvicorn asr.asr_api:app --host 0.0.0.0 --port 8001 --reload
```

The first startup downloads `facebook/wav2vec2-large-960h` from Hugging Face.
The model is approximately 1.2 GB and is cached under `model_cache/`. Later
startups reuse the cached files. The model is loaded once per API process.

In another terminal, verify the health-check endpoint:

```bash
curl http://localhost:8001/ping
```

Expected response:

```json
{"message":"pong"}
```

Interactive API documentation is available at
`http://localhost:8001/docs` while the service is running.

Transcribe an MP3 file:

```bash
curl -X POST http://localhost:8001/asr \
  -H "accept: application/json" \
  -F "file=@asr/cv-valid-dev/sample-000000.mp3;type=audio/mpeg"
```

PowerShell users should run the same command with `curl.exe`.

Example response:

```json
{
  "transcription": "BEFORE HE HAD TIME TO ANSWER",
  "duration": "20.7"
}
```

Uploaded files are decoded as mono 16 kHz audio and deleted immediately after
the request finishes, including when decoding or inference fails.

Run the API tests:

```bash
python -m pytest asr/test_asr_api.py
```

### Docker

The ASR service is containerized with Python 3.11, CPU-only PyTorch, FFmpeg,
and an unprivileged runtime user. Build and start the `asr-api` service from
the repository root:

```bash
docker compose -f asr/docker-compose.yml up --build -d
```

The first startup downloads the Wav2Vec2 model into the persistent
`htx-asr-model-cache` Docker volume. Monitor startup with:

```bash
docker compose -f asr/docker-compose.yml logs -f asr-api
```

Wait until the container reports `healthy`:

```bash
docker compose -f asr/docker-compose.yml ps
```

Test the container:

```bash
curl http://localhost:8001/ping

curl -X POST http://localhost:8001/asr \
  -F "file=@asr/cv-valid-dev/sample-000000.mp3;type=audio/mpeg"
```

Expected transcription response:

```json
{
  "transcription": "BE CAREFUL WITH YOUR PROGNOSTICATIONS SAID THE STRANGER",
  "duration": "5.1"
}
```

Verify that processed MP3 uploads are deleted from the container:

```bash
docker exec asr-api sh -c \
  "find /tmp -maxdepth 1 -type f -name '*.mp3' | wc -l"
```

The expected count after a request is `0`.

Test restart behavior:

```bash
docker restart asr-api
docker compose -f asr/docker-compose.yml ps
curl http://localhost:8001/ping
```

Stop and remove the container without deleting the cached model:

```bash
docker compose -f asr/docker-compose.yml down
```

To deliberately remove the model cache as well:

```bash
docker compose -f asr/docker-compose.yml down --volumes
```

#### Docker command reference

Start the service and rebuild its image:

```bash
docker compose -f asr/docker-compose.yml up --build -d
```

- `docker compose` manages services defined in a Compose YAML file.
- `-f asr/docker-compose.yml` selects the Compose file; here `-f` means
  **file**.
- `up` creates and starts the service, network, and volume.
- `--build` rebuilds the image before starting the service.
- `-d` uses detached mode so the container runs in the background.

Build the image without starting a container:

```bash
docker compose -f asr/docker-compose.yml build
```

- `build` creates or updates the image defined by the Compose service.

Start the existing image without requesting a rebuild:

```bash
docker compose -f asr/docker-compose.yml up -d
```

Follow the service logs:

```bash
docker compose -f asr/docker-compose.yml logs -f asr-api
```

- `logs` displays container output.
- `-f` after `logs` means **follow**, so new log lines remain visible.
- `asr-api` limits the output to that service.
- Press `Ctrl+C` to stop following logs; the detached container keeps running.

The meaning of `-f` depends on its position:

```text
docker compose -f FILE  -> select a Compose file
docker compose logs -f  -> follow new log output
```

Display the service status, health, and published ports:

```bash
docker compose -f asr/docker-compose.yml ps
```

- `ps` lists the containers belonging to the Compose project.

Run the temporary-file check inside the running container:

```bash
docker exec asr-api sh -c \
  "find /tmp -maxdepth 1 -type f -name '*.mp3' | wc -l"
```

- `docker exec` runs a command inside an existing container.
- `asr-api` is the container name.
- `sh -c` asks the shell to execute the following quoted command.
- `find /tmp` searches the temporary directory.
- `-maxdepth 1` prevents searching nested directories.
- `-type f` selects regular files.
- `-name '*.mp3'` selects MP3 files.
- `|` passes the matches to the next command.
- `wc -l` counts the matching files.

Restart the existing container:

```bash
docker restart asr-api
```

- `restart` stops and starts the named container.
- Restarting does not rebuild the image or delete the model-cache volume.

Stop and remove the Compose container and network:

```bash
docker compose -f asr/docker-compose.yml down
```

- `down` removes the project containers and network.
- The built image and named model-cache volume remain available.

Stop the project and also delete its named volumes:

```bash
docker compose -f asr/docker-compose.yml down --volumes
```

- `--volumes` also removes `htx-asr-model-cache`.
- Deleting this volume causes the model to download again on the next startup.

## Services

| Service | Local URL | Purpose |
| --- | --- | --- |
| ASR health check | `http://localhost:8001/ping` | Implemented |
| ASR inference | `http://localhost:8001/asr` | Implemented |
| Elasticsearch | `http://localhost:9200` | Store Common Voice records |
| Search UI | `http://localhost:3000` | Search and filter transcriptions |

Run instructions and verified curl examples will be added with each service.

## Dataset

The Common Voice audio files are intentionally excluded from Git because of
their size. The supplied `common_voice.zip` archive was inspected and only the
assessment's development subset was extracted under `asr/cv-valid-dev/`.

The extracted dataset was validated with the following results:

- 4,076 non-empty MP3 files
- 4,076 rows in `cv-valid-dev.csv`
- No duplicate CSV filenames
- Every CSV filename maps to exactly one extracted MP3
- Columns: `filename`, `text`, `up_votes`, `down_votes`, `age`, `gender`,
  `accent`, and `duration`
- Source audio decodes at 48 kHz and is resampled to 16 kHz by the ASR API

Verify the local file count from Git Bash:

```bash
find asr/cv-valid-dev -maxdepth 1 -type f -name "*.mp3" | wc -l
```

Expected result:

```text
4076
```

Raw MP3 files remain ignored by Git. The final `cv-valid-dev.csv`, including
the generated `generated_text` column, will be kept as a submission artifact.

### Batch transcription

Keep the ASR API running on port `8001`, then open a second terminal and run a
one-file smoke test:

```bash
python asr/cv-decode.py --max-files 1
```

After confirming that the first row contains a transcription, process all
remaining rows:

```bash
python asr/cv-decode.py
```

The decoder:

- uploads each MP3 to `POST /asr`
- adds the required `generated_text` column
- fills the existing `duration` column from the API response
- retries transient failures up to three times
- saves an atomic checkpoint every 25 successful transcriptions
- skips rows that already have `generated_text`, allowing interrupted runs to
  resume safely

A row is also considered complete when the API returned a duration but an
empty transcription. This preserves a genuine empty Wav2Vec2 result instead
of replacing it with reference text or retrying it indefinitely.

Useful options:

```bash
# Reprocess every row, including completed rows
python asr/cv-decode.py --overwrite

# Use a different API deployment
python asr/cv-decode.py --api-url http://example.com:8001/asr

# Display all available options
python asr/cv-decode.py --help
```

The script exits with status `1` if any rows fail after all retries. Failed
rows remain blank and can be retried by running the same command again.

## Elasticsearch backend

The backend runs Elasticsearch `8.19.2` as a two-node cluster:

- `es01` exposes `http://localhost:9200`
- `es02` is available only inside the Docker network
- each node uses a constrained 512 MB JVM heap and a 1.5 GB container limit
- each node stores data in its own persistent Docker volume
- the index uses one primary shard and one replica
- security is disabled for local assessment use, and port `9200` is bound only
  to `127.0.0.1`

Start both nodes from the repository root:

```bash
docker compose -f elastic-backend/docker-compose.yml up -d
```

Check that both nodes are healthy:

```bash
docker compose -f elastic-backend/docker-compose.yml ps

curl "http://localhost:9200/_cluster/health?pretty"
```

Create `cv-transcriptions` and bulk-index all 4,076 CSV records:

```bash
python elastic-backend/cv-index.py
```

The default run deletes and recreates the index. To keep the existing index
and overwrite documents using deterministic filename-based IDs:

```bash
python elastic-backend/cv-index.py --no-recreate
```

Indexer options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--csv` | `elastic-backend/cv-valid-dev.csv` | CSV source file |
| `--url` | `http://localhost:9200` | Elasticsearch endpoint |
| `--index` | `cv-transcriptions` | Target index name |
| `--chunk-size` | `500` | Documents per bulk request |
| `--no-recreate` | disabled | Preserve the index and upsert stable IDs |

The explicit mappings include:

| Field | Elasticsearch type |
| --- | --- |
| `generated_text` | `text` |
| `duration` | `float` |
| `age` | `keyword` |
| `gender` | `keyword` |
| `accent` | `keyword` |

Verify the document count:

```bash
curl "http://localhost:9200/cv-transcriptions/_count?pretty"
```

### Elasticsearch endpoint guide

Elasticsearch uses different endpoints depending on whether you need cluster
information, index metadata, a count, or matching documents.

| Endpoint | Purpose | Returns matching documents? |
| --- | --- | --- |
| `/` | Elasticsearch version and node information | No |
| `/_cluster/health` | Cluster status and node/shard health | No |
| `/_cat/nodes` | Compact list of cluster nodes | No |
| `/_cat/indices` | Compact list of indices and document counts | No |
| `/cv-transcriptions/_mapping` | Field names and Elasticsearch data types | No |
| `/cv-transcriptions/_count` | Number of documents matching a query | No |
| `/cv-transcriptions/_search` | Matching documents, scores, and `_source` data | Yes |

Check that Elasticsearch is reachable:

```bash
curl "http://localhost:9200/?pretty"
```

Check cluster health:

```bash
curl "http://localhost:9200/_cluster/health?pretty"
```

List both Elasticsearch nodes:

```bash
curl "http://localhost:9200/_cat/nodes?v"
```

List indices and stored document counts:

```bash
curl "http://localhost:9200/_cat/indices?v"
```

Inspect the explicit field mappings:

```bash
curl "http://localhost:9200/cv-transcriptions/_mapping?pretty"
```

Use `_count` when only the number of matching records is needed. It does not
return filenames or document contents:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_count?pretty" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"accent":"singapore"}}}'
```

Use `_search` when the matching audio filename and indexed data are needed:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "_source": ["filename", "accent", "generated_text", "duration"],
    "query": {
      "term": {
        "accent": "singapore"
      }
    }
  }'
```

The returned records are located under:

```text
hits.hits
```

Each result contains its deterministic `_id`, relevance `_score`, and indexed
fields under `_source`.

### Search query types

Use `match` for analyzed full-text fields such as `generated_text` and `text`.
Elasticsearch analyzes the query into words and calculates relevance scores:

Search generated transcriptions:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{"query":{"match":{"generated_text":"prognostications"}}}'
```

Use `term` for an exact value in keyword fields such as `age`, `gender`, and
`accent`. Keyword matching is exact and case-sensitive:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "_source": ["filename", "gender", "generated_text"],
    "query": {
      "term": {
        "gender": "female"
      }
    }
  }'
```

Use `range` for numeric fields such as `duration`:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "_source": ["filename", "duration", "generated_text"],
    "query": {
      "range": {
        "duration": {
          "gte": 5.0,
          "lte": 6.0
        }
      }
    }
  }'
```

The range operators are:

| Operator | Meaning |
| --- | --- |
| `gt` | greater than |
| `gte` | greater than or equal to |
| `lt` | less than |
| `lte` | less than or equal to |

Use a `bool` query to combine full-text search with exact filters:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "_source": ["filename", "accent", "duration", "generated_text"],
    "query": {
      "bool": {
        "must": [
          {"match": {"generated_text": "the boy"}}
        ],
        "filter": [
          {"term": {"accent": "us"}},
          {"range": {"duration": {"lte": 6.0}}}
        ]
      }
    }
  }'
```

- `must` contains full-text conditions that affect relevance `_score`.
- `filter` contains exact constraints that do not affect relevance.
- `_source` limits the fields returned, making results easier to read.

List available filter values and their document counts with an aggregation:

```bash
curl -X POST "http://localhost:9200/cv-transcriptions/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{
    "size": 0,
    "aggs": {
      "available_accents": {
        "terms": {
          "field": "accent",
          "size": 20
        }
      }
    }
  }'
```

`"size": 0` hides document hits because this request only needs aggregation
results. Accent values and counts appear under:

```text
aggregations.available_accents.buckets
```

Run the indexer unit tests:

```bash
python -m pytest elastic-backend/test_cv_index.py
```

Stop the cluster while retaining both data volumes:

```bash
docker compose -f elastic-backend/docker-compose.yml down
```

To remove the stored Elasticsearch data as well:

```bash
docker compose -f elastic-backend/docker-compose.yml down --volumes
```

## Deployment

The solution will be deployed to AWS using self-managed containers. Managed
cloud services will not be used.

Public deployment URL: **Not deployed yet**

## Assessment assumptions

- References to `cs-valid-dev.csv` in Tasks 3 and 4 are treated as typographical
  errors referring to `cv-valid-dev.csv`.
- ASR input is converted to mono audio sampled at 16 kHz before inference.
- The two Elasticsearch nodes may share one EC2 host for this assessment; this
  satisfies the container requirement but does not provide host-level high
  availability.

## Security

Do not commit credentials, `.env` files, downloaded model weights, raw audio,
or temporary uploads. Cloud secrets will be provided through environment
variables.
