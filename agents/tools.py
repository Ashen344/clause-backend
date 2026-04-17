"""
tools.py — Callable tools available to both agents.

Each function is registered with the function-calling interface.
The model decides which tool to call and with what arguments;
the agent loop executes it and feeds the result back.
"""

import os
import json
import time
import logging
import hashlib
import threading
from pathlib import Path

from elasticsearch import Elasticsearch
from redis import Redis
from google import genai

logger = logging.getLogger(__name__)

# ── Gemini Rate Limiter ───────────────────────────────────────────────────

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODEL_LITE = os.environ.get("GEMINI_MODEL_LITE", "gemini-2.5-flash")
GEMINI_MODEL_HEAVY = os.environ.get("GEMINI_MODEL_HEAVY", "gemini-2.5-pro")
GEMINI_MAX_REQUESTS_PER_MINUTE = int(os.environ.get("GEMINI_RPM", "10"))
GEMINI_MAX_REQUESTS_PER_DAY = int(os.environ.get("GEMINI_RPD", "300"))

# ── Local model (Ollama) config ──────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
LOCAL_MODEL_ENABLED = os.environ.get("LOCAL_MODEL_ENABLED", "false").lower() in ("true", "1", "yes")

# Task-to-model mapping: pick the right model weight for each task type
TASK_MODELS = {
    "chat":             GEMINI_MODEL_LITE,   # simple Q&A
    "analyze-text":     GEMINI_MODEL,        # structured analysis
    "generate-draft":   GEMINI_MODEL_HEAVY,  # full contract generation
    "detect-conflicts": GEMINI_MODEL_HEAVY,  # cross-contract reasoning
    "architect":        GEMINI_MODEL_HEAVY,  # agent: document generation
    "analyst":          GEMINI_MODEL,        # agent: clause analysis
}

# Tasks that are lightweight enough to run on the local model.
# These get routed to Ollama when LOCAL_MODEL_ENABLED is true.
# "ask-gemini-helper" is intentionally absent — it must always reach Gemini.
LOCAL_CAPABLE_TASKS = {"chat", "analyze-text"}


class GeminiRateLimiter:
    """Thread-safe rate limiter for Gemini API calls."""

    def __init__(self, rpm: int, rpd: int):
        self._rpm = rpm
        self._rpd = rpd
        self._minute_timestamps: list[float] = []
        self._day_count = 0
        self._day_start = time.time()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.time()

            # Reset daily counter if 24h passed
            if now - self._day_start > 86400:
                self._day_count = 0
                self._day_start = now

            if self._day_count >= self._rpd:
                raise RuntimeError(
                    f"Gemini daily limit reached ({self._rpd} requests/day). "
                    "Try again tomorrow."
                )

            # Clean timestamps older than 60s
            self._minute_timestamps = [
                t for t in self._minute_timestamps if now - t < 60
            ]

            if len(self._minute_timestamps) >= self._rpm:
                wait = 60 - (now - self._minute_timestamps[0])
                raise RuntimeError(
                    f"Gemini rate limit reached ({self._rpm} requests/min). "
                    f"Try again in {wait:.0f}s."
                )

            self._minute_timestamps.append(now)
            self._day_count += 1

    @property
    def usage(self) -> dict:
        with self._lock:
            now = time.time()
            recent = sum(1 for t in self._minute_timestamps if now - t < 60)
            return {
                "requests_this_minute": recent,
                "requests_today": self._day_count,
                "rpm_limit": self._rpm,
                "daily_limit": self._rpd,
            }


_rate_limiter = GeminiRateLimiter(
    rpm=GEMINI_MAX_REQUESTS_PER_MINUTE,
    rpd=GEMINI_MAX_REQUESTS_PER_DAY,
)


def get_rate_limiter() -> GeminiRateLimiter:
    return _rate_limiter


# ── Local model (Ollama) client ──────────────────────────────────────────

import requests as http_requests

_ollama_available: bool | None = None  # cached probe result


def check_ollama_health() -> bool:
    """Check if Ollama is reachable and the model is loaded."""
    global _ollama_available
    try:
        resp = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if resp.status_code != 200:
            _ollama_available = False
            return False
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        # Accept both "gemma3:4b" and "gemma3:4b-..." variants
        base_name = OLLAMA_MODEL.split(":")[0] if ":" in OLLAMA_MODEL else OLLAMA_MODEL
        _ollama_available = any(base_name in m for m in models)
        if not _ollama_available:
            logger.warning("Ollama running but model '%s' not found. Available: %s",
                           OLLAMA_MODEL, models)
        return _ollama_available
    except Exception as e:
        logger.debug("Ollama health check failed: %s", e)
        _ollama_available = False
        return False


def pull_ollama_model() -> bool:
    """Pull the configured model into Ollama. Called at startup if model is missing."""
    try:
        logger.info("Pulling Ollama model '%s' — this may take a few minutes on first run...",
                     OLLAMA_MODEL)
        resp = http_requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": OLLAMA_MODEL, "stream": False},
            timeout=600,
        )
        if resp.status_code == 200:
            logger.info("Ollama model '%s' pulled successfully", OLLAMA_MODEL)
            return True
        logger.error("Failed to pull model: HTTP %d", resp.status_code)
        return False
    except Exception as e:
        logger.error("Failed to pull Ollama model: %s", e)
        return False


def is_ollama_available() -> bool:
    """Return cached Ollama availability. Re-probes if not yet checked."""
    if _ollama_available is None:
        return check_ollama_health()
    return _ollama_available


def generate_text_local(messages: list[dict], max_tokens: int = 1024,
                        temperature: float = 0.3) -> str:
    """Generate text using the local Ollama model.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str}.
        max_tokens: Max output tokens.
        temperature: Sampling temperature.

    Returns:
        Generated text string.

    Raises:
        RuntimeError: If Ollama is unreachable or returns an error.
    """
    # Convert messages to Ollama chat format
    ollama_messages = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            role = "user"
        elif role == "model":
            role = "assistant"
        ollama_messages.append({"role": role, "content": msg["content"]})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }

    try:
        resp = http_requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=2220,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        logger.info("generate_text_local model=%s tokens=%d len=%d",
                     OLLAMA_MODEL,
                     data.get("eval_count", 0),
                     len(content))
        return content

    except http_requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out (120s)")
    except http_requests.exceptions.ConnectionError:
        raise RuntimeError(f"Cannot connect to Ollama at {OLLAMA_URL}")


# ── Config ─────────────────────────────────────────────────────────────────

ES_URL     = os.environ.get("ES_URL",     "http://localhost:9200")
INDEX_NAME = os.environ.get("INDEX_NAME", "clm_knowledge_base")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── Lazy client singletons ─────────────────────────────────────────────────

_es = None
_redis = None
_gemini = None


def _load_gemini_key() -> str:
    for path in ["/run/secrets/gemini_api_key",
                 str(Path(__file__).parent.parent / "injest" / "secrets" / "gemini_api_key.txt"),
                 str(Path(__file__).parent / "secrets" / "gemini_api_key.txt")]:
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("Gemini API key not found")
    return key


def get_es() -> Elasticsearch:
    global _es
    if _es is None:
        kwargs = {"request_timeout": 30}
        elastic_password_path = "/run/secrets/elastic_password"
        try:
            if os.path.exists(elastic_password_path):
                with open(elastic_password_path) as f:
                    password = f.read().strip()
                kwargs["basic_auth"] = ("elastic", password)
        except PermissionError:
            logger.debug("Cannot read %s, relying on credentials in ES_URL", elastic_password_path)
        _es = Elasticsearch(ES_URL, **kwargs)
    return _es


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(
            host=REDIS_HOST,
            port=int(REDIS_PORT),
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _redis


def get_gemini() -> genai.Client:
    global _gemini
    if _gemini is None:
        _gemini = genai.Client(api_key=_load_gemini_key())
    return _gemini


def generate_text(messages: list[dict], max_tokens: int = 2048, temperature: float = 0.3, task: str = None) -> str:
    """Generate text, routing to local model or Gemini based on task type.

    Routing logic:
      - If LOCAL_MODEL_ENABLED and task is in LOCAL_CAPABLE_TASKS and Ollama
        is healthy → use local model (saves API tokens).
      - Otherwise → use Gemini (with rate limiting and caching).

    Args:
        messages: List of {"role": "user"|"model", "content": str} dicts.
                  First message with role "system" is extracted as system_instruction.
        max_tokens: Max output tokens.
        temperature: Sampling temperature.
        task: Task type key (e.g. "chat", "architect", "detect-conflicts").
              Used to select the appropriate Gemini model from TASK_MODELS.

    Returns:
        Generated text string.
    """
    # ── Try local model for lightweight tasks ────────────────────────────
    use_local = (
        LOCAL_MODEL_ENABLED
        and task in LOCAL_CAPABLE_TASKS
        and is_ollama_available()
    )

    if use_local:
        try:
            logger.info(f"generate_text routing to LOCAL model ({OLLAMA_MODEL}) for task={task}")
            return generate_text_local(messages, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            logger.warning(f"Local model failed, falling back to Gemini: {e}")
            # Fall through to Gemini

    # ── Gemini path ──────────────────────────────────────────────────────
    model = TASK_MODELS.get(task, GEMINI_MODEL) if task else GEMINI_MODEL
    logger.info(f"generate_text using model={model} for task={task or 'default'}")

    # Check cache for identical prompts (only for low-temperature / deterministic calls)
    if temperature <= 0.3:
        content_for_hash = json.dumps(messages, sort_keys=True) + f"|{max_tokens}|{temperature}|{model}"
        gen_cache_key = f"gen:{hashlib.md5(content_for_hash.encode()).hexdigest()}"
        cached = cache_get(gen_cache_key)
        if cached:
            logger.info("generate_text cache hit")
            return cached
    else:
        gen_cache_key = None

    _rate_limiter.acquire()

    client = get_gemini()

    # Extract system instruction if present
    system_instruction = None
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = msg["content"]
        elif msg["role"] == "tool":
            chat_messages.append({"role": "user", "parts": [{"text": f"[TOOL_RESULT]\n{msg['content']}\n[/TOOL_RESULT]"}]})
        elif msg["role"] == "user":
            chat_messages.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] in ("assistant", "model"):
            chat_messages.append({"role": "model", "parts": [{"text": msg["content"]}]})

    # Gemini 2.5 models use thinking tokens that count against
    # max_output_tokens.  Set a thinking budget so the visible answer
    # isn't starved, and bump total tokens to accommodate both.
    is_thinking_model = "2.5" in model
    if is_thinking_model:
        thinking_budget = 1024
        total_tokens = max_tokens + thinking_budget
    else:
        total_tokens = max_tokens

    config = {
        "max_output_tokens": total_tokens,
        "temperature": temperature,
    }
    if is_thinking_model:
        config["thinking_config"] = {"thinking_budget": thinking_budget}
    if system_instruction:
        config["system_instruction"] = system_instruction

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=chat_messages,
                config=config,
            )
            # Extract all text parts from the response (Gemini 2.5 may
            # split output across multiple parts, e.g. thinking + answer)
            parts = (response.candidates[0].content.parts
                     if response.candidates and response.candidates[0].content
                     else [])
            text_parts = [p.text for p in parts if p.text and not getattr(p, "thought", False)]
            result_text = "\n".join(text_parts) if text_parts else (response.text or "")
            finish = (response.candidates[0].finish_reason
                      if response.candidates else None)
            logger.info(f"generate_text model={model} finish={finish} "
                        f"parts={len(parts)} text_len={len(result_text)}")
            if gen_cache_key:
                cache_set(gen_cache_key, result_text, ttl=1800)
            return result_text
        except Exception as e:
            error_str = str(e)
            if attempt < max_retries - 1 and ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "503" in error_str):
                wait_time = (2 ** attempt) * 2  # 2s, 4s, 8s
                logger.warning(f"Gemini API error (attempt {attempt + 1}), retrying in {wait_time}s: {error_str}")
                time.sleep(wait_time)
            else:
                raise


TEMPLATE_FILES = {
    "nda": "nda.txt",
    "msa": "msa.txt",
    "sow": "sow.txt",
    "sla": "sla.txt",
}


# ── Shared JSON parser ─────────────────────────────────────────────────────

def parse_tool_call(text: str) -> dict | None:
    """Extract tool call JSON from model output using balanced-brace parsing.

    Uses brace-depth counting instead of regex so nested JSON in argument
    values is handled correctly.  Returns a parsed dict with "name" and
    "arguments" keys, or None if no valid tool call is found.
    """
    start = 0
    while True:
        # Find the next opening brace
        idx = text.find("{", start)
        if idx == -1:
            break

        # Walk forward counting brace depth to find the matching close
        depth = 0
        end = -1
        for i in range(idx, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        if end == -1:
            # Unmatched brace — no point continuing
            break

        candidate = text[idx:end]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

        # Advance past this opening brace and try the next one
        start = idx + 1

    return None


# ── Tool 1: search_clauses ─────────────────────────────────────────────────

def search_clauses(query: str, top_k: int = 5, doc_type: str = None) -> str:
    """
    Embed the query with Gemini and run a kNN search on Elasticsearch.
    Returns the top_k most relevant clause chunks as a JSON string.

    Args:
        query:    Natural-language question or clause topic.
        top_k:    Number of results to return (default 5).
        doc_type: Optional filter — e.g. "SLA", "MSA", "NDA".
    """
    cache_key = f"search:{hashlib.md5(f'{query}{top_k}{doc_type}'.encode()).hexdigest()}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    # Embed the query
    result = get_gemini().models.embed_content(
        model="gemini-embedding-001",
        contents=query
    )
    query_vector = result.embeddings[0].values

    # Build kNN query
    knn_query = {
        "knn": {
            "field": "vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": top_k * 5
        }
    }

    # Optional doc_type filter
    if doc_type:
        knn_query["knn"]["filter"] = {
            "term": {"metadata.doc_type": doc_type.upper()}
        }

    response = get_es().search(index=INDEX_NAME, body=knn_query)
    hits = response["hits"]["hits"]

    results = [
        {
            "text":      h["_source"]["text"],
            "score":     round(h["_score"], 4),
            "source":    h["_source"]["metadata"].get("source", ""),
            "doc_type":  h["_source"]["metadata"].get("doc_type", ""),
            "customer":  h["_source"]["metadata"].get("customer", ""),
        }
        for h in hits
    ]

    output = json.dumps(results, indent=2)
    cache_set(cache_key, output, ttl=3600)
    return output


# ── Tool 2: render_template ────────────────────────────────────────────────

def render_template(doc_type: str, fields: dict) -> str:
    """
    Fill a contract template with the provided field values.
    Missing fields are left as {placeholder} so the model can flag them.

    Args:
        doc_type: One of nda, msa, sow, sla (case-insensitive).
        fields:   Dict of placeholder → value pairs.
    Returns:
        Rendered contract text.
    """
    doc_type = doc_type.lower()
    if doc_type not in TEMPLATE_FILES:
        return f"Error: unknown doc_type '{doc_type}'. Choose from: {', '.join(TEMPLATE_FILES)}"

    template_path = TEMPLATES_DIR / TEMPLATE_FILES[doc_type]
    if not template_path.exists():
        return f"Error: template file not found at {template_path}"

    template = template_path.read_text()

    # Replace known fields
    for key, value in fields.items():
        template = template.replace(f"{{{key}}}", str(value))

    return template


# ── Tool 3: cache_get / cache_set ─────────────────────────────────────────

def cache_get(key: str) -> str | None:
    """Retrieve a cached value from Redis. Returns None if not found."""
    try:
        return get_redis().get(key)
    except Exception:
        logger.warning("Cache get error for key %r", key, exc_info=True)
        return None


def cache_set(key: str, value: str, ttl: int = 3600) -> None:
    """Store a value in Redis with a TTL (seconds)."""
    try:
        get_redis().setex(key, ttl, value)
    except Exception:
        logger.warning("Cache set error for key %r", key, exc_info=True)


# ── Tool: ask_gemini ──────────────────────────────────────────────────────

def ask_gemini(question: str, context: str = "") -> str:
    """Delegate a question to Gemini and return the answer as a string.

    Called by the Ollama driver loop when the local model is not confident.
    Always routes to Gemini (task key not in LOCAL_CAPABLE_TASKS).
    """
    user_content = question
    if context:
        user_content = f"Context:\n{context}\n\nQuestion:\n{question}"

    messages = [
        {
            "role": "system",
            "content": (
                "You are helping a smaller local model complete a contract analysis task. "
                "Answer concisely and factually."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    return generate_text(messages, max_tokens=800, temperature=0.3, task="ask-gemini-helper")


# ── Tool schemas for Gemini function calling ───────────────────────────────
# These are passed to the model so it knows what tools are available
# and what arguments each one expects.

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "ask_gemini",
            "description": (
                "Ask Gemini (a larger model) a question when the local model "
                "cannot answer with confidence. Provide the question and optionally "
                "relevant excerpts from the contract as context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask Gemini"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional relevant excerpts from the contract"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_clauses",
            "description": (
                "Search the contract knowledge base for relevant clauses or passages. "
                "Use this to retrieve clause examples, definitions, and precedents "
                "before generating or analysing a document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language clause topic or question"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 5)",
                        "default": 5
                    },
                    "doc_type": {
                        "type": "string",
                        "description": "Optional filter: SLA, MSA, NDA, SOW",
                        "enum": ["SLA", "MSA", "NDA", "SOW"]
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "render_template",
            "description": (
                "Fill a predefined contract template (NDA, MSA, SOW, SLA) with "
                "specific field values provided by the user or extracted from context. "
                "Use this as the final step to produce the contract document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "description": "Contract type: nda, msa, sow, or sla",
                        "enum": ["nda", "msa", "sow", "sla"]
                    },
                    "fields": {
                        "type": "object",
                        "description": (
                            "Key-value pairs matching template placeholders. "
                            "Example: {\"party_a\": \"Acme Corp\", \"effective_date\": \"2024-01-01\"}"
                        )
                    }
                },
                "required": ["doc_type", "fields"]
            }
        }
    }
]
