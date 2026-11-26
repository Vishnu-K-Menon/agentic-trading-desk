"""The firm's research library: long-term memory that is searched by meaning.

Notes are embedded with FastEmbed and kept in a local Qdrant collection. Qdrant's local
mode lets only one process open the folder, so only the library MCP server uses this
module's store; each note is also mirrored to the database for the dashboard to read.
"""

import sys
import time
import uuid
from datetime import datetime
from .config import QDRANT_DIR
from .database import execute, rows

COLLECTION = "research"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384
MAX_NOTE_CHARS = 4000

_client = None
_embedder = None


def _store():
    """Open Qdrant and the embedding model on first use (the model is slow to load)."""
    global _client, _embedder
    if _client is None:
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient, models

        _embedder = TextEmbedding(EMBEDDING_MODEL)
        _client = QdrantClient(path=str(QDRANT_DIR))
        if not _client.collection_exists(COLLECTION):
            _client.create_collection(
                COLLECTION,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            )
    return _client, _embedder


def warm_up():
    """Do the slow loading now rather than inside the first request."""
    try:
        _store()
    except Exception as e:
        print(f"Research library could not be prepared: {e}", file=sys.stderr)


def _embed(text: str) -> list[float]:
    _, embedder = _store()
    return next(iter(embedder.embed([text]))).tolist()


def _clean_symbols(symbols: list[str] | None) -> list[str]:
    return sorted({symbol.strip().upper() for symbol in symbols or [] if symbol.strip()})


def store_research(trader: str, text: str, topic: str = "", symbols: list[str] | None = None) -> dict:
    """Add a research note to the library."""
    from qdrant_client import models

    text = text.strip()[:MAX_NOTE_CHARS]
    if not text:
        return {"stored": False, "error": "The note is empty"}
    client, _ = _store()
    note_id = str(uuid.uuid4())
    payload = {
        "trader": trader.strip().title(),
        "topic": topic.strip()[:200],
        "symbols": _clean_symbols(symbols),
        "text": text,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    vector = _embed(f"{payload['topic']}\n{text}")
    client.upsert(COLLECTION, points=[models.PointStruct(id=note_id, vector=vector, payload=payload)])
    execute(
        "INSERT INTO research_notes (id, created_at, trader, topic, symbols, text) VALUES (?, ?, ?, ?, ?, ?)",
        (note_id, time.time(), payload["trader"], payload["topic"], ",".join(payload["symbols"]), text),
    )
    return {"stored": True, "id": note_id}


def search_research(query: str, symbol: str = "", limit: int = 5) -> dict:
    """The notes closest in meaning to the query, optionally only those about one symbol."""
    from qdrant_client import models

    client, _ = _store()
    only_symbol = None
    if symbol.strip():
        only_symbol = models.Filter(
            must=[models.FieldCondition(key="symbols", match=models.MatchAny(any=[symbol.strip().upper()]))]
        )
    found = client.query_points(
        COLLECTION, query=_embed(query), query_filter=only_symbol, limit=max(1, min(limit, 10)), with_payload=True
    ).points
    notes = [
        {
            "relevance": round(point.score, 3),
            "date": point.payload.get("date"),
            "by": point.payload.get("trader"),
            "topic": point.payload.get("topic"),
            "symbols": point.payload.get("symbols"),
            "text": point.payload.get("text"),
        }
        for point in found
    ]
    return {"query": query, "notes": notes}


def list_notes(trader: str = "", limit: int = 50) -> list[dict]:
    """Stored notes, newest first, read from the database mirror (safe from any process)."""
    if trader:
        return rows(
            "SELECT id, created_at, trader, topic, symbols, text FROM research_notes "
            "WHERE lower(trader) = ? ORDER BY created_at DESC LIMIT ?",
            (trader.lower(), limit),
        )
    return rows(
        "SELECT id, created_at, trader, topic, symbols, text FROM research_notes ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
