# DPP Webhook Ingestion — Architecture & Design Decisions

This document explains what the tool does, how it is structured, and _why_ each technical decision was made the way it was.

---

## Overview

This is a Python CLI that signs and sends JSON payloads to a DPP (Digital Product Passport) system's webhook endpoint. The endpoint enforces a specific HMAC-SHA256 signing protocol — every request must carry a timestamp header and a signature header derived from both the timestamp and the payload body. Getting either wrong silently produces a `401` or `403` from the server.

The tool was written as a Python equivalent of a TypeScript reference implementation. Every decision in the signing layer traces back to matching the TypeScript behavior exactly.

---

## Signing Protocol

This is the core contract. Everything else in the codebase exists to produce a correctly signed HTTP request.

### Step 1 — Timestamp

```
X-DPP-Timestamp: 2026-06-16T08:55:35.788Z
```

The timestamp must match exactly what JavaScript's `new Date().toISOString()` produces:

- UTC timezone
- ISO 8601 format
- **Millisecond precision** (three decimal places on seconds)
- `Z` suffix (not `+00:00`)

**Why this matters:** The server re-derives the signature using the `X-DPP-Timestamp` header value it receives. If the timestamp format differs even by the suffix (`+00:00` vs `Z`), the signing input changes, and the signatures do not match.

Python's `datetime.isoformat()` defaults to `+00:00`. The implementation corrects this:

```python
# signing.py
from datetime import datetime, timezone

def utc_timestamp_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

# Output: "2026-06-16T08:55:35.788Z"
```

### Step 2 — Compact JSON Body

The payload must be serialized with **no whitespace**, matching JavaScript's `JSON.stringify(payload)`:

```python
# signing.py
import json

def compact_json(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
```

**Why `separators=(",", ":")`:** Python's `json.dumps` defaults to `", "` and `": "` (with spaces). The `,` and `:` override removes that whitespace. A single extra space in the body changes the byte sequence being signed, producing a different HMAC.

**Why `ensure_ascii=False`:** JavaScript's `JSON.stringify` does not escape non-ASCII characters. Python does by default. If the payload contains any Unicode characters (product names, place names, etc.), forcing ASCII escaping would produce a different byte sequence.

Example — same payload, both forms:

```python
payload = {"productName": "Müller Cell", "weight": 420}

# Wrong (Python default):
# '{"productName": "M\\u00fcller Cell", "weight": 420}'

# Correct:
json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
# '{"productName":"Müller Cell","weight":420}'
```

### Step 3 — Signing Input

Concatenate the timestamp and compact body with a `.` separator:

```
<X-DPP-Timestamp>.<compact-json-body>
```

Example:

```
2026-06-16T08:55:35.788Z.{"specVersion":"1.0","messageId":"abc-123","operation":"upsert"}
```

```python
# signing.py
signing_input = f"{timestamp}.{body}".encode("utf-8")
```

**Why UTF-8 encoding:** `hmac.new()` requires `bytes`. The payload may contain multi-byte Unicode characters (preserved by `ensure_ascii=False`), so UTF-8 is the correct encoding — it is also what JavaScript uses internally.

### Step 4 — HMAC-SHA256 Signature

```python
# signing.py
import hashlib
import hmac

signature = hmac.new(
    webhook_secret.encode("utf-8"),
    signing_input,
    hashlib.sha256,
).hexdigest()
```

The result is sent as the `X-DPP-Signature` header.

**Why HMAC over a plain hash:** HMAC binds the signature to a shared secret. A plain SHA-256 hash of the body could be replayed by anyone who intercepts the request. HMAC ensures only parties that hold `DPP_WEBHOOK_SECRET` can produce a valid signature.

**Why `hexdigest()`:** The TypeScript reference uses `.toString('hex')` on a Node.js `Buffer`. `hexdigest()` is the Python equivalent — lowercase hex string of the raw bytes.

### Complete Signing Flow — Example

```python
import hashlib
import hmac
import json
from datetime import datetime, timezone

def utc_timestamp_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

def compact_json(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

def sign(payload: dict, secret: str):
    timestamp = utc_timestamp_ms()                    # Step 1
    body      = compact_json(payload)                 # Step 2
    signing_input = f"{timestamp}.{body}".encode()    # Step 3
    signature = hmac.new(                             # Step 4
        secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-DPP-Timestamp": timestamp,
        "X-DPP-Signature": signature,
        "body": body,
    }

payload = {
    "specVersion": "1.0",
    "messageId": "unique-msg-id-013",
    "timestamp": "2026-05-22T10:00:00.000Z",
    "operation": "upsert",
}
result = sign(payload, secret="D-pjxQB-UvkrYHxeNRk7jZgo0zm9dWNsyGiJZqWBFSg")

# X-DPP-Timestamp : 2026-06-16T08:55:35.788Z  (changes each run)
# X-DPP-Signature : <64-char hex string>
# body            : {"specVersion":"1.0","messageId":"unique-msg-id-013",...}
```

### Known-Good Signature Vector

The test suite pins a fixed timestamp and secret to verify the implementation has not drifted:

```python
# tests/test_signing.py
payload = {"specVersion": "1.0", "messageId": "unique-msg-id-013"}
signed = sign_payload(
    payload=payload,
    webhook_secret="D-pjxQB-UvkrYHxeNRk7jZgo0zm9dWNsyGiJZqWBFSg",
    timestamp="2026-06-12T07:41:42.301Z",
)

assert signed.signature == "69ee91bc4ba7334fa4f74c3df6d3110f292b974884d7c083e872dc3d2eef9638"
```

This was cross-validated against the TypeScript reference and a Postman/cURL test. Any change to the signing algorithm will fail this test immediately.

---

## Module Structure

```
src/dpp_webhook/
├── signing.py   # HMAC signing — no I/O, no side effects
├── client.py    # HTTP POST — wraps urllib
├── flows.py     # DPP lifecycle logic — payload loading, serial injection
├── ui.py        # Terminal output, ANSI colors, tables
└── cli.py       # Argument parsing, command handlers, .env loading
```

Each layer has one responsibility and does not reach across into adjacent layers except through its public interface.

### `signing.py` — Core Cryptographic Layer

Owns everything cryptographic. Has no I/O, no side effects, no CLI awareness. Takes a payload (dict or string) and a secret, returns a frozen `SignedWebhookPayload` dataclass:

```python
@dataclass(frozen=True)
class SignedWebhookPayload:
    timestamp: str
    signature: str
    body: str       # compact JSON string

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-DPP-Timestamp": self.timestamp,
            "X-DPP-Signature": self.signature,
        }
```

**Why `frozen=True`:** A signed payload is an immutable value. Freezing the dataclass makes accidental mutation a hard error instead of a silent bug.

**Why a `headers` property:** The three required headers always travel together. Putting them on the signed object means nothing can forget one.

### `client.py` — HTTP Layer

Wraps `urllib.request` to POST a `SignedWebhookPayload`:

```python
def post_signed_payload(url, signed, timeout_seconds=30) -> WebhookResponse:
    request = Request(
        url=url,
        data=signed.body.encode("utf-8"),
        headers=signed.headers,
        method="POST",
    )
    ...
```

**Why `urllib` instead of `requests`:** The project has no third-party dependencies. `urllib` is part of the Python standard library and is sufficient for a single-endpoint POST. Avoiding `requests` means no dependency installation, no version pinning, and no supply chain surface area.

**Why catch `HTTPError` separately from `URLError`:** `urllib` raises `HTTPError` (a subclass of `URLError`) for 4xx/5xx responses. If not caught first, the error body is lost. The implementation reads the response body before re-raising as a `WebhookClientError` with the status code, reason, and body included in the error message — making debugging a failed request possible without a network inspector.

```python
except HTTPError as exc:
    error_body = exc.read().decode("utf-8", errors="replace")
    detail = {"status": exc.code, "reason": exc.reason, "body": error_body}
    raise WebhookClientError(json.dumps(detail, indent=2)) from exc
```

### `flows.py` — DPP Lifecycle Layer

Owns the three lifecycle operations (`initiate`, `activate`, `update`) and the logic for injecting the serial number into the correct location inside each payload template.

**Why separate payload files per operation:**

Each DPP operation has a different schema:

| Operation             | `operation` field | Serial location                                                |
| --------------------- | ----------------- | -------------------------------------------------------------- |
| `initiate` / `update` | `upsert`          | `data.identifierAndProductData.fields.uniqueBatteryIdentifier` |
| `activate`            | `status_update`   | top-level `unitIdentifierValue`                                |

Keeping three template files (`create_payload.json`, `activate_payload.json`, `update_payload.json`) makes it easy to add or modify fields for a specific operation without touching the others.

**Why a `SERIAL_PATH` tuple:**

```python
SERIAL_PATH = (
    "data",
    "identifierAndProductData",
    "fields",
    "uniqueBatteryIdentifier",
)
```

The serial number lives 4 levels deep in the `initiate`/`update` payload. Using a tuple of keys makes the path explicit, testable, and easy to update if the DPP schema evolves — rather than hardcoded string navigation.

**`OperationResult` as a value object:**

```python
@dataclass(frozen=True)
class OperationResult:
    operation: str
    serial: str
    message_id: str
    status: int | None  # None = dry-run
    body: str
    dry_run: bool

    @property
    def ok(self) -> bool:
        if self.dry_run:
            return True
        return self.status is not None and 200 <= self.status < 300
```

`ok` encodes the success rule once. The `workflow` command, which chains multiple operations, calls `result.ok` to decide whether to proceed. Dry-runs always succeed so the full pipeline can be previewed without a live server.

### `cli.py` — Entry Point and Command Layer

**Why `argparse` over `click` or `typer`:** Same reasoning as `urllib` — zero dependencies. `argparse` is standard library and fully sufficient for this number of subcommands.

**Why `load_dotenv()` is implemented manually:**

```python
def load_dotenv(path: Path = Path(".env")) -> None:
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:   # <— does not override shell env
            os.environ[key] = value
```

The critical behavior is `if key not in os.environ`. Shell-set variables always win over `.env`. This is the standard convention for 12-factor apps — the `.env` file provides developer defaults, but CI/CD or production environments set the real values in the shell and those are never silently overwritten.

### `ui.py` — Terminal Output Layer

Owns all ANSI color codes and formatting. Every other module that prints output calls into `ui` rather than formatting strings inline.

**Why centralize terminal formatting:**

- Color suppression is applied in one place (`_colors()` checks `sys.stdout.isatty()` and `NO_COLOR`)
- The `NO_COLOR` env var follows the [no-color.org](https://no-color.org) standard — the tool respects it automatically when output is piped or redirected
- Changing color scheme or output format requires editing one file

**Color semantics:**

| Color   | Meaning                    |
| ------- | -------------------------- |
| Cyan    | Field labels               |
| Green   | 2xx success status         |
| Yellow  | 4xx / dry-run              |
| Red     | 5xx / errors               |
| Magenta | Serial numbers             |
| Dim     | Signatures, secondary info |

---

## DPP Lifecycle

A DPP (Digital Product Passport) unit is identified by its serial number. The three operations must happen in order:

```
initiate  →  update (BMS data)  →  activate (publish)
```

### Payload Schemas

**`initiate` — `operation: upsert` with full product data**

```json
{
  "specVersion": "1.0",
  "messageId": "unique-msg-id-0000008787",
  "timestamp": "2026-05-22T10:00:00.000Z",
  "operation": "upsert",
  "data": {
    "identifierAndProductData": {
      "fields": {
        "batteryName": "Cleantron Battery Pack P4X",
        "uniqueBatteryIdentifier": "SN-A1B2C3D4E5F6"
      }
    }
  }
}
```

**`activate` — `operation: status_update` with serial at top level**

```json
{
  "specVersion": "1.0",
  "messageId": "unique-msg-id-01",
  "timestamp": "2026-05-22T10:00:00.000Z",
  "operation": "status_update",
  "unitIdentifierValue": "SN-A1B2C3D4E5F6",
  "status": "published"
}
```

**`update` — `operation: upsert` with BMS telemetry data**

```json
{
  "specVersion": "1.0",
  "messageId": "unique-msg-id-0000008787",
  "timestamp": "2026-05-22T10:00:00.000Z",
  "operation": "upsert",
  "data": {
    "performanceAndDurability": { ... },
    "identifierAndProductData": {
      "fields": {
        "uniqueBatteryIdentifier": "SN-A1B2C3D4E5F6"
      }
    }
  }
}
```

### `messageId` and `timestamp` Are Always Replaced

Before signing, `flows.prepare_payload()` always injects:

```python
payload["messageId"] = message_id or str(uuid4())   # fresh UUID per request
payload["timestamp"] = timestamp or utc_timestamp_ms()
```

The values in the template files are placeholders. Every request carries a unique `messageId` so the server can deduplicate and the `timestamp` inside the body stays consistent with the `X-DPP-Timestamp` header.

---

## Configuration

All credentials and URLs are loaded from environment variables. The `.env` file is a local developer convenience — it does not override variables already set in the shell.

| Variable                   | Used by                                  |
| -------------------------- | ---------------------------------------- |
| `DPP_WEBHOOK_SECRET`       | All commands (signing key)               |
| `DPP_WEBHOOK_URL`          | `send`, `initiate`, `update`, `workflow` |
| `DPP_WEBHOOK_ACTIVATE_URL` | `activate`, `workflow`                   |
| `DPP_ACTIVATE_URL`         | Fallback for activate URL                |

**Activate URL fallback chain** (checked in order):

1. `--activate-url` CLI flag
2. `DPP_WEBHOOK_ACTIVATE_URL`
3. `DPP_ACTIVATE_URL`

The two env var names exist because different teams use different naming conventions for the same endpoint.

---

## Workflow Command

`dpp-webhook workflow` runs the full `initiate → update → activate` pipeline for N DPPs. It was built for bulk testing and integration validation.

**Design decisions:**

- Phases run sequentially — all initiates complete before any updates start. This makes the console output easy to read and avoids race conditions on the server side.
- Each phase gate requires explicit confirmation (`[Y/n]`) unless `--yes` is passed. This prevents an accidental workflow run from flooding the server with live data.
- Failure in any phase prints the summary table and exits with code 1. Partial results are visible; already-created serials are shown in the table so they can be activated or cleaned up manually.
- The summary table renders a row per serial and a column per operation, color-coded by HTTP status:

```
  📊 Summary
╔══════════════════════╦════════════╦════════════╦════════════╗
║Serial                ║Initiate    ║Update      ║Activate    ║
╠══════════════════════╬════════════╬════════════╬════════════╣
║SN-A1B2C3D4E5F6       ║201         ║200         ║200         ║
╚══════════════════════╩════════════╩════════════╩════════════╝
```

---

## Testing

Tests live in `tests/test_signing.py` and use the standard library `unittest` module — no test framework dependency.

**What is tested:**

1. `compact_json` output matches the expected `JSON.stringify` shape byte-for-byte.
2. `sign_payload` produces a known HMAC for a fixed input — cross-validated against the TypeScript reference.
3. A full Postman/cURL payload also matches a known signature.
4. The CLI generates a fresh `messageId` by default on every call.
5. `--preserve-message-id` keeps the `messageId` from the template file unchanged.

**Run tests:**

```bash
python -m pytest tests/
# or
python -m unittest discover tests/
```

**Run a single test:**

```bash
python -m unittest tests.test_signing.SigningTests.test_signature_matches_known_hmac
```
