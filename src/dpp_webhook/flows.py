"""DPP lifecycle operations — payload loading, serial injection, signing, sending."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import post_signed_payload
from .signing import sign_payload, utc_timestamp_ms

EXAMPLES_DIR = Path("examples")
CREATE_PAYLOAD_PATH = EXAMPLES_DIR / "create_payload.json"
ACTIVATE_PAYLOAD_PATH = EXAMPLES_DIR / "activate_payload.json"
UPDATE_PAYLOAD_PATH = EXAMPLES_DIR / "update_payload.json"

DEFAULT_PAYLOAD_PATHS = {
    "initiate": CREATE_PAYLOAD_PATH,
    "activate": ACTIVATE_PAYLOAD_PATH,
    "update": UPDATE_PAYLOAD_PATH,
}

# Nested location of the serial number inside the initiate/update `data` block.
SERIAL_PATH = (
    "data",
    "identifierAndProductData",
    "fields",
    "uniqueBatteryIdentifier",
)


@dataclass(frozen=True)
class OperationResult:
    operation: str
    serial: str
    message_id: str
    status: int | None
    body: str
    dry_run: bool

    @property
    def ok(self) -> bool:
        if self.dry_run:
            return True
        return self.status is not None and 200 <= self.status < 300


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Payload root must be a JSON object: {path}")
    return payload


def get_serial(payload: dict[str, Any]) -> str | None:
    """Read the serial from the nested data block, falling back to the top-level
    unitIdentifierValue (used by activate/status_update payloads)."""
    node: Any = payload
    for key in SERIAL_PATH:
        if not isinstance(node, dict) or key not in node:
            node = None
            break
        node = node[key]
    if isinstance(node, str) and node:
        return node

    top_level = payload.get("unitIdentifierValue")
    return top_level if isinstance(top_level, str) and top_level else None


def set_serial(payload: dict[str, Any], serial: str) -> None:
    """Write the serial wherever the payload expects it: the nested
    productSerialNumber (if a data block exists) and the top-level
    unitIdentifierValue (if present in the template)."""
    node: Any = payload
    for key in SERIAL_PATH[:-1]:
        if not isinstance(node, dict) or not isinstance(node.get(key), dict):
            node = None
            break
        node = node[key]
    if isinstance(node, dict):
        node[SERIAL_PATH[-1]] = serial

    # Only set unitIdentifierValue if the template already has it
    # (activate payloads have it; initiate/update use the nested path above)
    if "unitIdentifierValue" in payload:
        payload["unitIdentifierValue"] = serial


def generate_serial(prefix: str = "SN") -> str:
    """Build a unique serial number suitable for mass initiate."""
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def prepare_payload(
    payload_path: Path,
    serial: str | None,
    *,
    message_id: str | None = None,
    timestamp: str | None = None,
    battery_name: str | None = None,
) -> dict[str, Any]:
    payload = load_payload(payload_path)
    if serial is not None:
        set_serial(payload, serial)
    # Inject battery name if provided (initiate/update payloads only)
    if battery_name is not None:
        payload["data"]["identifierAndProductData"]["fields"]["batteryName"] = battery_name
        print(f"\n  🏷️  Battery name set to: {battery_name}")
    payload["messageId"] = message_id or str(uuid4())
    payload["timestamp"] = timestamp or utc_timestamp_ms()
    return payload


def run_operation(
    operation: str,
    serial: str | None,
    *,
    secret: str,
    url: str,
    payload_path: Path | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 30,
    message_id: str | None = None,
    battery_name: str | None = None,
) -> OperationResult:
    """Load the operation's payload, inject the serial + fresh metadata, sign it,
    and POST it (unless dry_run)."""
    path = payload_path or DEFAULT_PAYLOAD_PATHS[operation]
    payload = prepare_payload(path, serial, message_id=message_id, battery_name=battery_name)
    resolved_serial = get_serial(payload) or (serial or "")
    signed = sign_payload(payload, secret)

    if dry_run:
        return OperationResult(
            operation=operation,
            serial=resolved_serial,
            message_id=str(payload["messageId"]),
            status=None,
            body=signed.body,
            dry_run=True,
        )

    response = post_signed_payload(url, signed, timeout_seconds=timeout_seconds)
    return OperationResult(
        operation=operation,
        serial=resolved_serial,
        message_id=str(payload["messageId"]),
        status=response.status,
        body=response.body,
        dry_run=False,
    )
