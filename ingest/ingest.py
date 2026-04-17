import os
import sys
import hashlib
import logging
import argparse
from google import genai
from langchain_text_splitters import RecursiveCharacterTextSplitter
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from redis import Redis
from rq import Queue as RQueue, Worker

from extractor import extract, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

# --- Configuration ---
def _load_gemini_key() -> str:
    secret_path = "/run/secrets/gemini_api_key"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "Gemini API key not found. "
            "Provide it via Docker secret at /run/secrets/gemini_api_key "
            "or set the GEMINI_API_KEY environment variable."
        )
    return key


# Lazy singleton Gemini client
_gemini_client = None

def _get_gemini_client() -> genai.Client:
    """Return a shared Gemini client, initializing it on first call."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=_load_gemini_key())
    return _gemini_client


def _load_elastic_password() -> str | None:
    """Read the Elasticsearch password from Docker secret if available."""
    secret_path = "/run/secrets/elastic_password"
    if os.path.exists(secret_path):
        try:
            with open(secret_path) as f:
                return f.read().strip()
        except PermissionError:
            logger.debug("Cannot read %s; relying on credentials in ES_URL", secret_path)
    return None


def _validate_config():
    """Validate required environment variables at startup."""
    errors = []

    es_url = os.environ.get("ES_URL", "").strip()
    if not es_url:
        errors.append("ES_URL is not set")
    elif not (es_url.startswith("http://") or es_url.startswith("https://")):
        errors.append(f"ES_URL does not look like a valid URL: {es_url!r}")

    redis_host = os.environ.get("REDIS_HOST", "").strip()
    if not redis_host:
        errors.append("REDIS_HOST is not set")

    redis_port_str = os.environ.get("REDIS_PORT", "").strip()
    if redis_port_str:
        try:
            port = int(redis_port_str)
            if not (1 <= port <= 65535):
                errors.append(f"REDIS_PORT must be between 1 and 65535, got {port}")
        except ValueError:
            errors.append(f"REDIS_PORT is not a valid integer: {redis_port_str!r}")
    # REDIS_PORT has a default so absence is not fatal, but a bad value is.

    if errors:
        for msg in errors:
            logger.error("Config error: %s", msg)
        sys.exit(1)


ES_URL      = os.environ.get("ES_URL",      "http://localhost:9200")
INDEX_NAME  = os.environ.get("INDEX_NAME",  "clm_knowledge_base")
REDIS_HOST  = os.environ.get("REDIS_HOST",  "localhost")
REDIS_PORT  = int(os.environ.get("REDIS_PORT",  6379))
QUEUE_NAME  = os.environ.get("QUEUE_NAME",  "contract_tasks")
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", 600))

EMBED_BATCH_SIZE = 100  # Gemini supports up to 100 texts per embed call


def _build_es_client() -> Elasticsearch:
    """Build Elasticsearch client with optional auth and a request timeout."""
    password = _load_elastic_password()
    kwargs = {"request_timeout": 30}
    if password:
        kwargs["basic_auth"] = ("elastic", password)
    return Elasticsearch(ES_URL, **kwargs)

es = _build_es_client()

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=2000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ".", " "]
)

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "text":   {"type": "text"},
            "vector": {
                "type":       "dense_vector",
                "dims":       3072,
                "index":      True,
                "similarity": "cosine"
            },
            "metadata": {
                "properties": {
                    "source":    {"type": "keyword"},
                    "doc_type":  {"type": "keyword"},
                    "customer":  {"type": "keyword"},
                    "chunk_id":      {"type": "integer"},
                    "file_type":     {"type": "keyword"},   # e.g. pdf, txt, csv ...
                    "content_hash":  {"type": "keyword"}    # SHA-256 for dedup
                }
            }
        }
    }
}


def ensure_index():
    # In the ES 8.x Python client, indices.exists() raises a 400/404
    # instead of returning False when the index is missing.
    # We use a raw HTTP GET and treat 404 as "does not exist".
    try:
        es.indices.get(index=INDEX_NAME)
        logger.info("Index already exists: %s", INDEX_NAME)
        return
    except Exception as e:
        err = str(e)
        if "index_not_found_exception" in err or "404" in err:
            pass   # expected -- index does not exist yet, create it below
        else:
            logger.error("Could not reach Elasticsearch: %s", e)
            logger.error("Is it running? Check: curl http://localhost:9200")
            sys.exit(1)

    try:
        es.indices.create(index=INDEX_NAME, mappings=INDEX_MAPPING["mappings"])
        logger.info("Created index: %s", INDEX_NAME)
    except Exception as e:
        logger.error("Failed to create index: %s", e)
        sys.exit(1)


# -- Dedup helpers ----------------------------------------------------------

MIN_CHUNK_LENGTH = 50   # skip chunks shorter than this (whitespace, headers, etc.)


def _file_content_hash(text: str) -> str:
    """Return a SHA-256 hex digest for the extracted text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _already_indexed(source_name: str, content_hash: str) -> bool:
    """Check if this exact file (by name + content hash) is already in the index."""
    try:
        resp = es.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "filter": [
                        {"term": {"metadata.source": source_name}},
                        {"term": {"metadata.content_hash": content_hash}},
                    ]
                }
            },
            size=1,
            _source=False,
        )
        return resp["hits"]["total"]["value"] > 0
    except Exception:
        return False   # index may not exist yet; proceed with ingestion


def _delete_old_chunks(source_name: str):
    """Remove previously indexed chunks for a file before re-ingesting."""
    try:
        es.delete_by_query(
            index=INDEX_NAME,
            query={"term": {"metadata.source": source_name}},
            refresh=True,
        )
        logger.info("Cleared old chunks for %s", source_name)
    except Exception as e:
        logger.warning("Could not clear old chunks for %s: %s", source_name, e)


# -- Core ingestion ---------------------------------------------------------

def ingest_document(file_path: str, doc_type: str = "SLA", customer: str = "Unknown"):
    """
    Extract -> chunk -> embed (batched) -> index (bulk) a single file of any supported format.
    """
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    source_name = os.path.basename(file_path)
    logger.info("Ingesting: %s", source_name)
    client = _get_gemini_client()

    # 1. Extract plain text (format-aware)
    text = extract(file_path)
    if not text.strip():
        logger.error("No text extracted from %s, skipping.", file_path)
        return

    # 2. Dedup check — skip if identical content already indexed
    content_hash = _file_content_hash(text)
    if _already_indexed(source_name, content_hash):
        logger.info("Skipping %s — already indexed with same content.", source_name)
        return

    # Remove stale chunks from a previous version of this file
    _delete_old_chunks(source_name)

    # 3. Chunk and filter out tiny fragments
    chunks = text_splitter.split_text(text)
    chunks = [c for c in chunks if len(c.strip()) >= MIN_CHUNK_LENGTH]
    logger.info("Chunks: %d", len(chunks))

    if not chunks:
        logger.warning("No meaningful chunks from %s, skipping.", source_name)
        return

    # 4. Embed chunks in batches, collect bulk actions
    actions = []
    for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[batch_start: batch_start + EMBED_BATCH_SIZE]

        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=batch
        )

        for offset, (chunk, embedding_obj) in enumerate(zip(batch, result.embeddings)):
            chunk_id = batch_start + offset
            actions.append({
                "_index": INDEX_NAME,
                "_source": {
                    "text":   chunk,
                    "vector": embedding_obj.values,
                    "metadata": {
                        "source":       source_name,
                        "doc_type":     doc_type,
                        "customer":     customer,
                        "chunk_id":     chunk_id,
                        "file_type":    ext,
                        "content_hash": content_hash,
                    }
                }
            })

    # 5. Bulk-index all actions in one request
    success_count, errors = bulk(es, actions, raise_on_error=False)
    if errors:
        logger.error("Bulk indexing had %d error(s) for %s", len(errors), source_name)
    logger.info("Indexed %d chunks from %s", success_count, source_name)


def ingest_folder(folder_path: str, doc_type: str, customer: str):
    """Ingest every supported file in a folder."""
    files = [
        os.path.join(folder_path, f)
        for f in sorted(os.listdir(folder_path))
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    ]
    if not files:
        exts = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        logger.error("No supported files found in %s.", folder_path)
        logger.info("Supported extensions: %s", exts)
        sys.exit(1)

    logger.info("Found %d file(s) in %s", len(files), folder_path)
    for f in files:
        ingest_document(f, doc_type=doc_type, customer=customer)


# -- RQ async support -------------------------------------------------------

def enqueue_document(file_path: str, doc_type: str, customer: str):
    """Push a single file ingestion job onto the RQ queue."""
    from tasks import analyze_contract
    conn = Redis(host=REDIS_HOST, port=REDIS_PORT)
    q = RQueue(QUEUE_NAME, connection=conn)
    job = q.enqueue(analyze_contract, file_path, doc_type, customer,
                    job_timeout=JOB_TIMEOUT)
    logger.info("Enqueued job %s -> %s", job.id, os.path.basename(file_path))
    return job.id


def start_worker():
    conn = Redis(host=REDIS_HOST, port=REDIS_PORT)
    queues = [RQueue(QUEUE_NAME, connection=conn)]
    logger.info("[worker] Listening on '%s' @ %s:%s", QUEUE_NAME, REDIS_HOST, REDIS_PORT)
    ensure_index()
    Worker(queues, connection=conn).work()


# -- CLI --------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    _validate_config()

    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    parser = argparse.ArgumentParser(
        description="CLM Knowledge Base -- Universal Ingestion Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported file types: {supported}

Examples:
  # Ingest a single file (any format)
  python ingest.py --file /data/input/contracts.txt --doc-type SLA --customer Acme
  python ingest.py --file /data/input/dataset.csv  --doc-type dataset
  python ingest.py --file /data/input/report.xlsx
  python ingest.py --file /data/input/brief.docx   --customer BetaCorp

  # Ingest an entire folder (all supported formats)
  python ingest.py --folder /data/input --doc-type MSA --customer BetaCorp

  # Async -- enqueue for background processing
  python ingest.py --file /data/input/contracts.txt --enqueue

  # Start the RQ worker
  python ingest.py --worker

  # Create the Elasticsearch index and exit
  python ingest.py --init-index
        """
    )

    parser.add_argument("--file",       help="Path to a file to ingest")
    parser.add_argument("--folder",     help="Path to a folder -- ingests all supported files")
    parser.add_argument("--doc-type",   default="SLA",     help="Document type tag (e.g. SLA, MSA, dataset)")
    parser.add_argument("--customer",   default="Unknown", help="Customer / dataset name")
    parser.add_argument("--enqueue",    action="store_true", help="Enqueue --file for async ingestion")
    parser.add_argument("--worker",     action="store_true", help="Start the RQ worker (blocking)")
    parser.add_argument("--init-index", action="store_true", help="Create the ES index and exit")

    args = parser.parse_args()

    if args.worker:
        start_worker()
        return

    ensure_index()

    if args.init_index:
        sys.exit(0)

    if args.file:
        if not os.path.isfile(args.file):
            logger.error("File not found: %s", args.file)
            sys.exit(1)
        if args.enqueue:
            enqueue_document(args.file, doc_type=args.doc_type, customer=args.customer)
        else:
            ingest_document(args.file, doc_type=args.doc_type, customer=args.customer)

    elif args.folder:
        if not os.path.isdir(args.folder):
            logger.error("Folder not found: %s", args.folder)
            sys.exit(1)
        if args.enqueue:
            files = [
                os.path.join(args.folder, f)
                for f in sorted(os.listdir(args.folder))
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
            ]
            for f in files:
                enqueue_document(f, doc_type=args.doc_type, customer=args.customer)
        else:
            ingest_folder(args.folder, doc_type=args.doc_type, customer=args.customer)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
