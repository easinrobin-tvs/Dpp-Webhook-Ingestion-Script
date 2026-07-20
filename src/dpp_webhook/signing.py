from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any


@dataclass(frozen=True)
class SignedWebhookPayload:
    timestamp: str
    signature: str
    body: str

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-DPP-Timestamp": self.timestamp,
            "X-DPP-Signature": self.signature,
        }


def utc_timestamp_ms() -> str:
    """Return JS-like new Date().toISOString() timestamp."""
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def compact_json(payload: Any) -> str:
    """Match JSON.stringify(payload) for plain JSON-compatible objects."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def sign_payload(
    payload: Any,
    webhook_secret: str,
    timestamp: str | None = None,
) -> SignedWebhookPayload:
    # If payload is a dict with a timestamp field, use it as the signing
    # timestamp so body and header always agree. Otherwise generate fresh.
    if timestamp is None and isinstance(payload, dict) and "timestamp" in payload:
        timestamp = str(payload["timestamp"])
    timestamp = timestamp or utc_timestamp_ms()
    body = payload if isinstance(payload, str) else compact_json(payload)
    signing_input = f"{timestamp}.{body}".encode("utf-8")
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).hexdigest()
    return SignedWebhookPayload(timestamp=timestamp, signature=signature, body=body)
