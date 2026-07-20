# DPP Webhook Ingestion CLI

Python CLI for DPP webhook ingestion — authenticate, create connections, and run end-to-end DPP lifecycle workflows (initiate → update → activate).

Uses HMAC-SHA256 signing. No third-party dependencies — pure Python stdlib.

## Quick Start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Webhook variables:**

| Variable | Description |
|----------|-------------|
| `DPP_WEBHOOK_SECRET` | HMAC-SHA256 signing secret |
| `DPP_WEBHOOK_URL` | Ingestion endpoint URL |
| `DPP_WEBHOOK_ACTIVATE_URL` | Activate endpoint URL |

**OAuth2 variables** (needed for connection management commands):

| Variable | Description |
|----------|-------------|
| `DPP_SSO_URL` | OAuth2 token endpoint base URL |
| `DPP_REALM` | Tenant/realm identifier |
| `DPP_CLIENT_ID` | OAuth2 client ID (default: `client.frontend`) |
| `DPP_USERNAME` | User email for password grant |
| `DPP_PASSWORD` | User password |
| `DPP_BASE_URL` | DPP API base URL |

`.env` is loaded automatically on startup and does not override shell variables.

---

## workflow

Runs the full initiate → update → activate pipeline for N DPPs. Supports interactive connection selection and battery name customization.

```bash
dpp-webhook workflow                    # default: 1 DPP
dpp-webhook workflow --count 2 --yes
dpp-webhook workflow --dry-run --yes
```

**Interactive flow:**

1. Select or create a webhook connection
2. Optionally customize the battery name
3. Run N DPPs through all three stages
4. Summary table at the end

Use `--yes` to skip prompts and use the current connection.

---

## Other Commands

```
dpp-webhook <command> [options]

  connect       Create a webhook connection with interactive setup
  connections   List all webhook connections
  health        Check health of a webhook connection
  generate      Print signed headers and body (no HTTP call)
  send          Send signed payload to webhook URL
  initiate      Create a DPP (upsert)
  activate      Publish a DPP by serial (status_update)
  update        BMS-like update of a DPP by serial (upsert)
```

### connect

Create a new webhook connection. Authenticates via OAuth2, creates the connection, and saves the webhook URL/secret to `.env`.

```bash
dpp-webhook connect
dpp-webhook connect --product-id "01KQYD3G8PB93P4BRD4GFDWXC5"
```

### connections

List all webhook connections for the authenticated user.

```bash
dpp-webhook connections
```

### health

Check health status of a webhook connection.

```bash
dpp-webhook health
dpp-webhook health --connection-id 01KV62G32NV20A9XK9R2ZJ9J0T
```

### generate / send

`generate` prints signed headers and body without making an HTTP call.

`send` signs the payload and POSTs it to the webhook URL.

```bash
dpp-webhook generate --secret "YOUR_SECRET"
dpp-webhook send --secret "YOUR_SECRET" --url "https://..."
dpp-webhook send --dry-run
```

| Option | Description |
|--------|-------------|
| `--secret` | Webhook secret (env: `DPP_WEBHOOK_SECRET`) |
| `--url` | Ingestion URL (env: `DPP_WEBHOOK_URL`) |
| `--payload` | Payload JSON file (default: `examples/payload.json`) |
| `--dry-run` | Print signed request without sending |
| `--timeout` | HTTP timeout in seconds (default: 30) |

### DPP Lifecycle (initiate / activate / update)

Each lifecycle stage uses its own payload template:

| Stage | Operation | Template |
|--------|-----------|----------|
| Initiate | `upsert` | `examples/create_payload.json` |
| Update | `upsert` | `examples/update_payload.json` |
| Activate | `status_update` | `examples/activate_payload.json` |

```bash
dpp-webhook initiate                    # serial auto-generated
dpp-webhook update --serial SN-...
dpp-webhook activate --serial SN-...
```

---

## Output

Color-coded output in interactive terminals:

- **Cyan** — field labels
- **Green** — 2xx success
- **Yellow** — 4xx response / dry-run
- **Red** — 5xx response / errors

Response bodies are pretty-printed as JSON. Disable colors with `NO_COLOR=1`.

## Signing

Python compact JSON matches `JSON.stringify()`:

```python
json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
```

Signature input: `<X-DPP-Timestamp>.<compact-json-body>`

Timestamp format: `2026-06-15T14:00:00.000Z`
