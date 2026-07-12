"""
Semantic Cache for Sanarip Med AI
Uses Redis + Gemini embeddings + cosine similarity to cache LLM responses.
Hit > 95% similarity → return cached response instantly (saves API call).
"""
import os
import json
import math
import time

# ── Cosine similarity ──
def cosine_similarity(vec_a: list, vec_b: list) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

# ── Redis helpers ──
REDIS_PREFIX = "semcache:"
SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.95"))

MAX_CACHE_ENTRIES = 500
CACHE_TTL = 86400 * 7  # 7 days

def _get_redis():
    """Lazy import of redis_client (avoids circular import)."""
    try:
        from telegram_bot import redis_client
        return redis_client
    except Exception:
        return None

def check_cache(query_embedding: list) -> str | None:
    """Check if a similar query exists in cache. Returns cached response or None."""
    r = _get_redis()
    if not r or not query_embedding:
        return None

    try:
        # Scan cached entries
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"{REDIS_PREFIX}*", count=50)
            for key in keys:
                raw = r.get(key)
                if not raw:
                    continue
                entry = json.loads(raw)
                cached_vec = entry.get("v", [])
                if cosine_similarity(query_embedding, cached_vec) >= SIMILARITY_THRESHOLD:
                    print(f"[SemCache] HIT (similarity > {SIMILARITY_THRESHOLD})")
                    return entry.get("r", "")
            if cursor == 0:
                break
    except Exception as e:
        print(f"[SemCache] Check error: {e}")
    return None

def store_cache(query_embedding: list, response: str):
    """Store a query-response pair in Redis cache."""
    r = _get_redis()
    if not r or not query_embedding or not response:
        return

    try:
        # Limit cache size
        key_count = len(r.keys(f"{REDIS_PREFIX}*"))
        if key_count >= MAX_CACHE_ENTRIES:
            # Delete oldest entry
            oldest = r.keys(f"{REDIS_PREFIX}*")
            if oldest:
                oldest_key = min(oldest, key=lambda k: float(json.loads(r.get(k) or '{"t":0}').get("t", 0)))
                r.delete(oldest_key)

        entry = {
            "v": query_embedding,
            "r": response,
            "t": time.time()
        }
        import hashlib
        h = hashlib.md5(response.encode('utf-8')).hexdigest()
        cache_key = f"{REDIS_PREFIX}{h}"
        r.setex(cache_key, CACHE_TTL, json.dumps(entry))


        print(f"[SemCache] Stored (total: {key_count + 1})")
    except Exception as e:
        print(f"[SemCache] Store error: {e}")
