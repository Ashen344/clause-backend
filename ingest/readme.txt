# CLM Knowledge Base — Ingestion Service

Extracts text from PDFs, chunks it, embeds it with Gemini, and indexes into Elasticsearch.
Supports both **synchronous** (inline) and **asynchronous** (RQ queue) ingestion.

## Architecture

```
                ┌─────────────────────────────────┐
  CLI / upload.py ──enqueue──► Redis (contract_tasks queue)
                                        │
                                        ▼
                                   RQ Worker
                                  (analyze_contract)
                                        │
                              ingest_document()
                                        │
                         ┌─────────────┴──────────────┐
                         ▼                             ▼
                   Gemini Embed              Elasticsearch Index
```

## Quick Start

### 1. Configure environment
```bash
cp .env.example .env
# Edit .env — set GEMINI_API_KEY and PDF_DIR
```

### 2. Build & start all services
```bash
docker compose up -d --build
# Starts: redis, elasticsearch, worker (listens for jobs)
```

### 3. Ingest documents

**Synchronous** (blocks until done — good for small batches):
```bash
docker compose run --rm ingest \
  --file /data/input/contract.pdf --doc-type SLA --customer Acme
```

**Async via `--enqueue`** (returns immediately, worker processes in background):
```bash
docker compose run --rm ingest \
  --file /data/input/contract.pdf --doc-type SLA --customer Acme --enqueue

# Enqueue a whole folder at once:
docker compose run --rm ingest \
  --folder /data/input --doc-type MSA --customer BetaCorp --enqueue
```

**Async via `upload.py`** (saves bytes to disk, then enqueues):
```bash
docker compose run --rm ingest python upload.py \
  /data/input/contract.pdf --doc-type SLA --customer Acme

# Check job status:
docker compose run --rm ingest python upload.py contract.pdf \
  --status <job_id>
```

**Only create the ES index:**
```bash
docker compose run --rm ingest --init-index
```

---

## CLI Reference

### ingest.py
```
Options:
  --file        PATH      Path to a single PDF file
  --folder      PATH      Path to a folder of PDFs
  --doc-type    TEXT      SLA, MSA, SOW, etc. (default: SLA)
  --customer    TEXT      Customer name (default: Unknown)
  --enqueue               Send to RQ queue instead of processing inline
  --worker                Start the RQ worker (blocking)
  --init-index            Create the Elasticsearch index and exit
```

### upload.py
```
positional:   file        Path to a local PDF file
  --doc-type  TEXT        Document type (default: SLA)
  --customer  TEXT        Customer name (default: Unknown)
  --status    JOB_ID      Check status of an existing RQ job
```

---

## Environment Variables

| Variable        | Default                    | Description                    |
|-----------------|----------------------------|--------------------------------|
| `GEMINI_API_KEY`| *(required)*               | Google Gemini API key          |
| `ES_URL`        | `http://localhost:9200`    | Elasticsearch URL              |
| `INDEX_NAME`    | `clm_knowledge_base`       | Target index name              |
| `REDIS_HOST`    | `localhost`                | Redis hostname                 |
| `REDIS_PORT`    | `6379`                     | Redis port                     |
| `QUEUE_NAME`    | `contract_tasks`           | RQ queue name                  |
| `JOB_TIMEOUT`   | `600`                      | Max seconds per job            |
| `UPLOAD_DIR`    | `/data/uploads`            | Where uploaded PDFs are stored |
| `PDF_DIR`       | `./data`                   | Host folder mounted to /data/input |

---

## Running without Docker Compose

```bash
pip install -r requirements.txt

export GEMINI_API_KEY=your_key
export ES_URL=http://localhost:9200
export REDIS_HOST=localhost

# Terminal 1 — start the worker
python ingest.py --worker

# Terminal 2 — enqueue a file
python ingest.py --file contract.pdf --doc-type SLA --customer Acme --enqueue

# Or upload + enqueue in one step
python upload.py contract.pdf --doc-type SLA --customer Acme
```






