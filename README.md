# HTX xData AIE Technical Assessment

This repository contains an Automatic Speech Recognition (ASR) service,
Common Voice transcription workflow, Elasticsearch backend, Search UI, and
AWS deployment design for the HTX xData technical assessment.

## Contents

- [Prerequisites](#prerequisites)
- [Python setup](#python-setup)
- [Project structure](#project-structure)
- [ASR API](#asr-api)
  - [Docker](#docker)
    - [Docker command reference](#docker-command-reference)
- [Services](#services)
- [Dataset](#dataset)
  - [Batch transcription](#batch-transcription)
- [Elasticsearch backend](#elasticsearch-backend)
  - [Elasticsearch endpoint guide](#elasticsearch-endpoint-guide)
  - [Search query types](#search-query-types)
- [Search UI](#search-ui)
  - [Architecture](#architecture)
  - [Run with Docker](#run-with-docker)
  - [Local development](#local-development)
- [Integrated local deployment](#integrated-local-deployment)
- [Test suites](#test-suites)
- [Public deployment](#public-deployment)
  - [Architecture](#architecture-1)
  - [EC2 startup and reboot verification](#ec2-startup-and-reboot-verification)
- [Assessment assumptions](#assessment-assumptions)
  - [Dataset interpretation](#dataset-interpretation)
  - [ASR service](#asr-service)
  - [Elasticsearch](#elasticsearch)
  - [Search UI interpretation](#search-ui-interpretation)
  - [AWS deployment resources](#aws-deployment-resources)
- [Security](#security)

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

A Python virtual environment is required when Python files are run directly on
the development computer or EC2 host. This applies to commands such as:

```bash
uvicorn asr.asr_api:app --host 0.0.0.0 --port 8001
python asr/cv-decode.py
python elastic-backend/cv-index.py
python -m pytest
```

The virtual environment keeps the versions from `requirements.txt` isolated
from the operating system's Python installation and from packages used by
other projects.

A host-side Python virtual environment is not required for the ASR API when it
runs through Docker. The ASR image already contains Python 3.11 and its pinned
dependencies in an isolated container filesystem. Therefore, this command does
not depend on the host `.venv`:

```bash
docker compose up --build -d
```

The host environment is still needed when running supporting Python scripts
outside the containers. For example, the EC2 deployment uses a small
`.deploy-venv` to run the host-side Elasticsearch indexer:

```bash
python3 -m venv .deploy-venv
.deploy-venv/bin/pip install elasticsearch==8.19.2
.deploy-venv/bin/python elastic-backend/cv-index.py
```

Creating `.venv` is therefore necessary for local development, testing, batch
transcription, or indexing, but optional when only starting and using the
already-containerized services.

## Project structure

```text
.
|-- asr/                  # ASR API, batch decoder, tests, and container files
|-- deployment-design/    # AWS architecture design PDF
|-- elastic-backend/      # Elasticsearch cluster, CSV, indexer, and tests
|-- search-ui/            # React UI, Express proxy, tests, and container files
|-- .env.example          # Environment-variable template
|-- docker-compose.yml    # Complete four-container deployment
|-- requirements.txt      # Pinned Python dependencies
`-- README.md              # Setup, operation, testing, and deployment guide
```

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
| ASR health check | `http://localhost:8001/ping` | Confirm model service health |
| ASR inference | `http://localhost:8001/asr` | Transcribe multipart MP3 uploads |
| Elasticsearch | `http://localhost:9200` | Store and query Common Voice records |
| Search UI | `http://localhost:3000` | Search and filter transcriptions |

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
the generated `generated_text` column, is tracked as a submission artifact in
both the ASR and Elasticsearch directories.

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

## Search UI

The Search UI is a minimal React application built with Elastic Search UI. It
provides:

- full-text search over `generated_text`
- duration range filters
- exact age, gender, and accent filters
- result cards showing filename, transcription, duration, and metadata
- ten results per page with pagination
- loading, empty-result, and error states
- responsive desktop and mobile layouts

### Architecture

The browser communicates only with the Search UI container:

```text
Browser :3000
    |
    | POST /api/search
    v
Express proxy in search-ui container
    |
    | private Docker network
    v
Elasticsearch es01:9200
```

The React client uses Elastic's `ApiProxyConnector`. The Express server uses
`ElasticsearchAPIConnector` and a server-owned query configuration. Browser
requests are sanitized to allow only:

- search terms up to 200 characters
- 10, 20, or 50 results per page
- filters for `duration`, `age`, `gender`, and `accent`

The Elasticsearch hostname and any future credentials remain server-side.
The browser bundle does not contain `es01:9200` or a public Elasticsearch URL.

### Run with Docker

Start and index Elasticsearch first:

```bash
docker compose -f elastic-backend/docker-compose.yml up -d
python elastic-backend/cv-index.py
```

The Elasticsearch Compose project creates the external
`htx-elastic-network` used by Search UI.

Build and start Search UI:

```bash
docker compose -f search-ui/docker-compose.yml up --build -d
```

Check container health:

```bash
docker compose -f search-ui/docker-compose.yml ps
curl "http://localhost:3000/api/health"
```

Open the application:

```text
http://localhost:3000
```

Example searches:

- `prognostications` for full-text matching
- accent `singapore` for one exact filter result
- duration `5 to 10 seconds` for a numeric range filter
- combined search and filters for narrower results

Stop Search UI:

```bash
docker compose -f search-ui/docker-compose.yml down
```

### Local development

Install dependencies and run tests:

```bash
cd search-ui
npm install
npm test
```

Start the Express proxy on port `3001`:

```bash
PORT=3001 npm start
```

In a second terminal, start Vite on port `3000`:

```bash
cd search-ui
npm run dev
```

Vite proxies `/api` requests to port `3001`. On PowerShell, set the proxy port
with:

```powershell
$env:PORT = "3001"
npm start
```

Create the production frontend build:

```bash
npm run build
```

The production container serves the compiled React application and proxy from
the same Express process on port `3000`.

## Integrated local deployment

The root `docker-compose.yml` starts the complete assessment stack on the
shared `htx-stack-network`:

- ASR API at `http://localhost:8001`
- Two-node Elasticsearch cluster at `http://localhost:9200`
- Search UI and server-side proxy at `http://localhost:3000`

Create the active environment configuration:

```bash
cp .env.example .env
```

The defaults are:

```ini
ASR_MODEL_ID=facebook/wav2vec2-large-960h
ELASTICSEARCH_INDEX=cv-transcriptions
```

`.env.example` is committed as a configuration template. The active `.env`
file is machine-specific and excluded from Git.

Start and build the complete stack from the repository root:

```bash
docker compose up --build -d
docker compose ps
```

If the images have already been built, start without rebuilding:

```bash
docker compose up -d --no-build
```

The Compose file reuses the named ASR model-cache and Elasticsearch data
volumes, so restarting the stack does not normally download the model or erase
the index. Each service uses `restart: unless-stopped`, allowing Docker to
restart the containers after an EC2 or host reboot.

The Elasticsearch containers start without an application index on a fresh
machine. Create and populate `cv-transcriptions` after the cluster is healthy:

```bash
python elastic-backend/cv-index.py
```

Verify the integrated stack:

```bash
docker compose ps
curl "http://localhost:8001/ping"
curl "http://localhost:3000/api/health"
curl "http://localhost:9200/_cluster/health?pretty"
curl "http://localhost:9200/cv-transcriptions/_count?pretty"
```

Expected results include four healthy containers, two Elasticsearch nodes, and
4,076 indexed documents.

Stop the stack while retaining the model and index data:

```bash
docker compose down
```

Do not add `--volumes` unless you deliberately want to delete the downloaded
model cache and both Elasticsearch data volumes.

## Test suites

Run all Python unit tests from the repository root:

```bash
python -m pytest -q
```

Run the Search UI proxy tests:

```bash
cd search-ui
npm install
npm test
```

The implemented suites cover ASR request handling and cleanup, batch decoding,
Elasticsearch document conversion and indexing behavior, and Search UI proxy
request sanitization.

## Public Deployment

The solution is deployed on an Ubuntu 24.04 AWS EC2 instance using the root
Compose stack. It uses a 40 GiB gp3 EBS volume, host swap, persistent Docker
volumes, and `vm.max_map_count=262144` for Elasticsearch. Elasticsearch port
`9200` is bound to loopback and is not exposed by the EC2 security group.

### Architecture

[View the AWS deployment architecture diagram](deployment-design/design.pdf).

The diagram presents both the deployed runtime services and the data
preparation/indexing workflow:

1. The EC2 security group permits Search UI traffic on port `3000`, ASR API
   traffic on port `8001`, and SSH on port `22` from the candidate's IP only.
   Elasticsearch port `9200` is not publicly exposed.
2. The root Compose project runs `search-ui`, `asr-api`, `es01`, and `es02` on
   the private `htx-stack-network` Docker bridge network.
3. Browser searches reach the React application and Express proxy in
   `search-ui`. The proxy sends server-controlled search requests to
   `http://es01:9200`; the browser never connects directly to Elasticsearch.
4. MP3 uploads reach `asr-api`, which decodes and resamples audio, runs the
   Wav2Vec2 model, returns transcription and duration, and deletes the temporary
   upload.
5. `cv-decode.py` represents the offline Common Voice transcription workflow,
   while `cv-index.py` is the administrative indexing workflow that creates and
   populates `cv-transcriptions`. Neither script is a continuously running
   container. When `cv-index.py` runs on the EC2 host, it connects through the
   loopback mapping at `http://localhost:9200`; the Docker-only hostname
   `http://es01:9200` is used by `search-ui` inside `htx-stack-network`.
6. `es01` and `es02` form the two-node Elasticsearch cluster. One primary shard
   and one replica distribute the index across the two persistent data volumes.
7. The EC2 gp3 EBS root disk stores the Docker engine data, including
   `htx-asr-model-cache`, `htx-es01-data`, and `htx-es02-data`. The repository,
   CSV files, logs, and other host files are also stored on EBS but are not
   separate Docker named volumes.

Search UI:

http://13.251.154.217:3000

ASR API health check:

http://13.251.154.217:8001/ping

The public endpoints are available only while the EC2 instance and containers
are running. If the instance uses an auto-assigned public IP instead of an
Elastic IP, this URL must be updated after an EC2 stop/start cycle.

### EC2 startup and reboot verification

After starting or rebooting EC2:

```bash
cd ~/HTX-MAP-Keith-Ang-Kee-Chun
docker compose ps
```

Docker is enabled as a system service and the Compose services use
`restart: unless-stopped`, so existing containers return automatically after a
reboot. Verify the recovered deployment with:

```bash
curl "http://localhost:8001/ping"
curl "http://localhost:3000/api/health"
curl "http://localhost:9200/cv-transcriptions/_count?pretty"
```

If the containers were manually stopped with `docker compose stop` before the
EC2 instance was stopped, resume them with:

```bash
docker compose start
```

## Assessment assumptions

### Dataset interpretation

| Assumption | Interpretation | Rationale |
| --- | --- | --- |
| CSV filename | References to `cs-valid-dev.csv` in Tasks 3 and 4 mean `cv-valid-dev.csv`. | The supplied dataset and the other assessment instructions consistently use the `cv-valid-dev` name. |
| Completed row | A row is complete when the API returns a valid duration, even if `generated_text` is empty. | An empty string can be a genuine Wav2Vec2 CTC result. It is preserved instead of being replaced with reference text or retried indefinitely. |

### ASR service

| Choice | Value | Rationale |
| --- | --- | --- |
| Input format | Mono, 16 kHz | The selected Wav2Vec2 model was trained for 16 kHz speech, so uploaded audio is mixed to mono and resampled before inference. |
| Python runtime | Python 3.11 | The selected PyTorch, Transformers, librosa, and FastAPI versions have stable compatible releases for this interpreter. |
| PyTorch build | CPU-only | The target EC2 instance has no GPU, so CUDA libraries and GPU runtime requirements are unnecessary. |
| Audio decoder | FFmpeg | FFmpeg provides reliable MP3 decoding before librosa performs mono conversion and resampling. |
| Runtime user | Unprivileged `asr` user | A compromised API process does not receive root permissions inside the container. |
| Memory limit | 5 GiB | Wav2Vec2 weights, PyTorch tensors, decoded audio, inference activations, and Python runtime memory can coexist during a request. The limit provides inference headroom while placing a ceiling on the largest service in the shared 8 GiB host. It is a maximum, not permanently reserved memory. |
| CPU limit | 2 CPUs | The EC2 instance provides two vCPUs and inference is CPU-only, so the service can use the available compute capacity while Docker still schedules the other lightweight services. |

### Elasticsearch

| Choice | Value | Rationale |
| --- | --- | --- |
| Cluster placement | Two containers on one EC2 host | This satisfies the two-node container requirement for the assessment, although it does not provide host-level high availability. |
| JVM heap per node | 512 MiB fixed minimum and maximum | The index contains only 4,076 documents and does not require a large search or aggregation heap. A fixed heap provides predictable use and avoids JVM heap resizing. |
| Container memory per node | 1.5 GiB | Elasticsearch uses native memory, thread stacks, direct buffers, and the operating-system file cache outside the JVM heap. The additional capacity supports these requirements while keeping both nodes within the host budget. |
| Primary shards | 1 | One primary shard is sufficient for the small assessment index and avoids unnecessary shard overhead. |
| Replicas | 1 | One replica places a second copy on the other Elasticsearch node and allows the expected two-node cluster to reach green health. |
| `vm.max_map_count` | `262144` | Elasticsearch uses many memory-mapped regions for Lucene index files. This value satisfies the host prerequisite and allows both nodes to start reliably on Ubuntu. |

### Search UI interpretation

| Field | Search UI behavior | Rationale |
| --- | --- | --- |
| `generated_text` | Analyzed full-text search | Users enter words and phrases from generated transcriptions. |
| `duration` | Numeric range filter | Duration is numeric metadata and is most useful for intervals such as 5 to 10 seconds. |
| `age` | Exact-value filter | Age values are categorical metadata. |
| `gender` | Exact-value filter | Gender values are categorical metadata. |
| `accent` | Exact-value, filterable facet | Accent values are categorical metadata and benefit from facet-value filtering. |

This interpretation allows users to query and narrow results using all five
required fields without applying text analysis to numeric or categorical
metadata.

| Choice | Value | Rationale |
| --- | --- | --- |
| Client connector | Elastic `ApiProxyConnector` | Browser searches are sent only to the application-owned `/api` endpoint. |
| Server connector | `ElasticsearchAPIConnector` | The Express server owns the Elasticsearch connection and query execution. |
| Query configuration | Server-owned | Elasticsearch hostname, future credentials, searchable fields, result fields, and permitted facets remain controlled by the server rather than trusted to the browser. |
| Container memory | 512 MiB | The container serves a compiled React bundle and one lightweight Express process. The limit covers Node.js, HTTP handling, and short-lived search responses without materially competing with ASR and Elasticsearch. |

### AWS deployment resources

| Resource | Value | Rationale |
| --- | --- | --- |
| EC2 instance | `m7i-flex.large` | It is a credit-eligible general-purpose instance that can host the complete assessment stack on one machine. |
| vCPUs | 2 | The two vCPUs provide the compute used by CPU-only ASR inference while also scheduling Elasticsearch, Search UI, Docker, and Ubuntu. |
| Physical RAM | 8 GiB | This accommodates the model, two deliberately constrained Elasticsearch nodes, Search UI, Docker, and Ubuntu for the assessment workload. |
| Operating system | Ubuntu 24.04 LTS | It is a current long-term-support release with security updates and supported Docker packages. |
| Host swap | 8 GiB | Concurrent model loading, Elasticsearch startup, and Docker builds can temporarily approach physical-RAM capacity. Swap supplies emergency backing memory to reduce out-of-memory termination risk; it is not intended as normal working memory. |
| EBS capacity | 40 GiB | The disk stores Ubuntu, Docker images and build layers, Python and Node dependencies, the approximately 1.2 GB ASR model cache, the repository, logs, and both Elasticsearch data volumes, with working space for extraction and updates. |
| EBS type | `gp3` | General-purpose SSD performance suits model loading, Docker builds, and the small-index read/write workload. |
| EBS performance | 3,000 IOPS and 125 MiB/s | The gp3 baseline provides predictable performance without adding provisioned-performance cost. |
| Persistent volumes | `htx-asr-model-cache`, `htx-es01-data`, `htx-es02-data` | Each stateful owner has an independent lifecycle. Model files and both Elasticsearch nodes' data survive container and EC2 restarts. |

These values form a credit-conscious, single-instance budget suitable for the
4,076-record dataset and light demonstration traffic. They are not intended
for production-scale performance or high availability.

## Security

Do not commit credentials, `.env` files, downloaded model weights, raw audio,
or temporary uploads. Cloud secrets will be provided through environment
variables.
