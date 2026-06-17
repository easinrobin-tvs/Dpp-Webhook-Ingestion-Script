# DPP Webhook Ingestion

Python CLI that signs and sends DPP webhook payloads using HMAC-SHA256 — a Python equivalent of the TypeScript webhook signing flow.

**Signing flow:**

1. Build JSON payload body.
2. Generate `X-DPP-Timestamp` in UTC ISO format with milliseconds and `Z`.
3. Sign `<timestamp>.<body>` using HMAC-SHA256 and the webhook secret.
4. POST with `Content-Type`, `X-DPP-Timestamp`, and `X-DPP-Signature` headers.

No third-party dependencies — pure Python stdlib.

---

## Quick Start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Configuration

All flags have environment variable equivalents. Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Environment Variable       | Description                |
| -------------------------- | -------------------------- |
| `DPP_WEBHOOK_SECRET`       | HMAC-SHA256 signing secret |
| `DPP_WEBHOOK_URL`          | Ingestion endpoint URL     |
| `DPP_WEBHOOK_ACTIVATE_URL` | Activate endpoint URL      |

`.env` is loaded automatically on startup and does not override variables already set in the shell.

---

## Commands

```
dpp-webhook <command> [options]

Commands:
  generate    Print signed headers and body (no HTTP call)
  send        Send signed payload to webhook URL
  create      Create a DPP (upsert); generates a serial if omitted
  activate    Publish/activate a DPP by serial (status_update)
  update      BMS-like update of a published DPP by serial (upsert)
  workflow    Run create → update → activate for N DPPs end to end
```

---

## generate

Prints the signed request headers and full pretty-printed body without making any HTTP call. Useful for inspecting or copying the signed output.

```bash
dpp-webhook generate --secret "YOUR_SECRET"
```

Using env vars:

```bash
export DPP_WEBHOOK_SECRET="YOUR_SECRET"
dpp-webhook generate
```

**Options:**

| Flag                    | Description                                                    |
| ----------------------- | -------------------------------------------------------------- |
| `--secret`              | Webhook secret. Defaults to `DPP_WEBHOOK_SECRET`.              |
| `--payload`             | Payload JSON file. Defaults to `examples/payload.json`.        |
| `--timestamp`           | Override `X-DPP-Timestamp`. Defaults to current UTC timestamp. |
| `--message-id`          | Override `messageId` in payload. Defaults to a generated UUID. |
| `--preserve-message-id` | Keep `messageId` from the payload file unchanged.              |

---

## send

Signs and POSTs the payload to the webhook ingestion URL. Shows a formatted request summary with colored output, status code, and pretty-printed response body.

```bash
dpp-webhook send \
  --secret "YOUR_SECRET" \
  --url "https://YOUR_BASE_URL/webhooks/dpps/YOUR_ID"
```

Using env vars:

```bash
export DPP_WEBHOOK_SECRET="YOUR_SECRET"
export DPP_WEBHOOK_URL="https://YOUR_BASE_URL/webhooks/dpps/YOUR_ID"

dpp-webhook send
```

Dry run — prints the signed request without sending:

```bash
dpp-webhook send --dry-run
```

Custom payload file:

```bash
dpp-webhook send --payload path/to/another-payload.json
```

**Options:**

| Flag                    | Description                                             |
| ----------------------- | ------------------------------------------------------- |
| `--secret`              | Webhook secret. Defaults to `DPP_WEBHOOK_SECRET`.       |
| `--url`                 | Ingestion URL. Defaults to `DPP_WEBHOOK_URL`.           |
| `--payload`             | Payload JSON file. Defaults to `examples/payload.json`. |
| `--timestamp`           | Override `X-DPP-Timestamp`.                             |
| `--message-id`          | Override `messageId`. Defaults to a generated UUID.     |
| `--preserve-message-id` | Keep `messageId` from the payload file.                 |
| `--dry-run`             | Print signed request without sending.                   |
| `--timeout`             | HTTP timeout in seconds. Defaults to `30`.              |

---

## DPP Lifecycle

A DPP unit is identified by its **serial number** (`productSerialNumber`), surfaced as `unitIdentifierValue` in activate and update payloads. Each lifecycle operation has its own payload file:

```
examples/create_payload.json     # operation: upsert (full data)
examples/activate_payload.json   # operation: status_update (publish by serial)
examples/update_payload.json     # operation: upsert (BMS-like update)
```

### create

Creates a DPP. Generates a serial automatically if `--serial` is omitted.

```bash
dpp-webhook create

# Or supply your own serial
dpp-webhook create --serial SN-XXXXXXXXXXXX
```

### activate

Publishes a created DPP by serial.

```bash
dpp-webhook activate --serial SN-XXXXXXXXXXXX
```

Uses `DPP_WEBHOOK_ACTIVATE_URL` or `DPP_ACTIVATE_URL` for the endpoint URL (falls back to `DPP_WEBHOOK_URL` if neither is set).

### update

BMS-like update on a published DPP.

```bash
dpp-webhook update --serial SN-XXXXXXXXXXXX
```

**Options (create / activate / update):**

| Flag        | Description                                                                           |
| ----------- | ------------------------------------------------------------------------------------- |
| `--serial`  | Serial number. If omitted, `create` generates one; `activate`/`update` prompt for it. |
| `--secret`  | Webhook secret. Defaults to `DPP_WEBHOOK_SECRET`.                                     |
| `--url`     | Endpoint URL. Defaults to `DPP_WEBHOOK_URL` (or activate URL for `activate`).         |
| `--payload` | Override default payload JSON file for the operation.                                 |
| `--dry-run` | Print signed request without sending.                                                 |
| `--timeout` | HTTP timeout in seconds. Defaults to `30`.                                            |

Each command prints the serial and the suggested next command on success.

---

## workflow

Runs the full create → update → activate pipeline for N DPPs in sequence. Pauses for confirmation between phases (skip with `--yes`). Prints a live summary table at the end.

```bash
# 3 DPPs, interactive confirmations
dpp-webhook workflow

# 5 DPPs, non-interactive
dpp-webhook workflow --count 5 --yes

# Preview without sending
dpp-webhook workflow --dry-run --yes
```

**Options:**

| Flag             | Description                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| `--count`        | Number of DPPs to create. Defaults to `3`.                                  |
| `--yes`          | Skip all confirmation prompts.                                              |
| `--secret`       | Webhook secret. Defaults to `DPP_WEBHOOK_SECRET`.                           |
| `--url`          | Ingestion URL. Defaults to `DPP_WEBHOOK_URL`.                               |
| `--activate-url` | Activate URL. Defaults to `DPP_WEBHOOK_ACTIVATE_URL` or `DPP_ACTIVATE_URL`. |
| `--dry-run`      | Print all requests without sending.                                         |
| `--timeout`      | HTTP timeout in seconds. Defaults to `30`.                                  |

---

## Output & Colors

All commands produce color-coded output in interactive terminals:

- **Cyan** — field labels
- **Magenta** — serial numbers
- **Green** — 2xx response status
- **Yellow** — 4xx response status / dry-run indicators
- **Red** — 5xx response status / errors
- **Dim** — HMAC signatures, secondary info

Response bodies are automatically pretty-printed as JSON with syntax highlighting (keys, strings, numbers, booleans).

To disable colors, set the standard `NO_COLOR` environment variable:

```bash
NO_COLOR=1 dpp-webhook send --dry-run
```

Colors are also suppressed automatically when output is piped or redirected (non-tty stdout).

---

## Signing Notes

Python compact JSON matches `JSON.stringify(payload)`:

```python
json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
```

Signature input format:

```
<X-DPP-Timestamp>.<compact-json-body>
```

Timestamp format matches JavaScript `new Date().toISOString()`:

```
2026-06-15T14:00:00.000Z
```
