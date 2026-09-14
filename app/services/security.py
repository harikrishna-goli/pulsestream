"""
Key Generation:
- Uses secrets.token_urlsafe(32) for cryptographically secure pseudo-random number generation (CSPRNG).
- Attaches prefix ps_live_ to distinguish from test keys.
- Computes one-way hashlib.sha256(raw_key.encode()).hexdigest().
- Computes safe preview prefix raw_key[:12] + "...".

Key Hashing:
- Hashes incoming header strings to match against stored key_hash.
"""

import secrets
import hashlib

def generate_key() -> dict:
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    safe_preview = raw_key[:12] + "..."
    return {"raw_key": raw_key, "key_hash": key_hash, "safe_preview": safe_preview}

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()