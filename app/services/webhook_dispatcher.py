import hmac
import hashlib
import json
import httpx
from typing import Dict, Any

def generate_hmac_signature(secret: str, payload: Dict[str, Any]) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

async def dispatch_webhook(target_url: str, secret: str, payload: Dict[str, Any]) -> bool:
    signature = generate_hmac_signature(secret, payload)
    headers = {
        "Content-Type": "application/json",
        "X-PulseStream-Signature": f"sha256={signature}",
        "User-Agent": "PulseStream-Dispatcher/1.0"
    }
    
    # Retry with exponential backoff
    delays = [0.1, 0.2, 0.4]
    async with httpx.AsyncClient(timeout=5.0) as client:
        for delay in delays:
            try:
                resp = await client.post(target_url, json=payload, headers=headers)
                if resp.is_success:
                    return True
            except Exception:
                pass
    return False
