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
  connect       Create a new webhook connection with interactive setup
  connections   List all webhook connections
  health        Check health of a webhook connection
  generate      Print signed headers and body (no HTTP call)
  send          Send signed payload to webhook URL
  initiate      Create a DPP (upsert); generates a serial if omitted
  activate      Publish/activate a DPP by serial (status_update)
  update        BMS-like update of a published DPP by serial (upsert)
  workflow      Run initiate → update → activate for N DPPs end to end
```

---

## connect

Creates a new webhook connection with interactive setup. This command handles OAuth2 authentication, connection creation, and automatic `.env` file configuration.

```bash
# Interactive mode - will prompt for credentials and product ID
dpp-webhook connect

# Provide product ID directly
dpp-webhook connect --product-id "01KQYD3G8PB93P4BRD4GFDWXC5"

# Non-interactive mode with all credentials
dpp-webhook connect \
  --product-id "01KQYD3G8PB93P4BRD4GFDWXC5" \
  --yes
```

**Interactive Flow:**

1. **Credential Check**: Checks if OAuth2 credentials exist in `.env`
2. **Credential Prompt**: If missing, prompts for SSO URL, Realm ID, Username, Password, Base URL
3. **Credential Save**: Saves provided credentials to `.env` for future use
4. **Product ID Prompt**: Asks for DPP product ID (if not provided via `--product-id`)
5. **Connection Name**: Asks for connection name (optional, auto-generated if empty)
6. **OAuth2 Authentication**: Authenticates with DPP API using password grant
7. **Connection Creation**: Creates webhook connection via `POST /connections`
8. **`.env` Update**: Automatically updates `.env` with:
   - `DPP_WEBHOOK_URL` - Full webhook URL
   - `DPP_WEBHOOK_SECRET` - Generated secret for HMAC signing
   - `DPP_WEBHOOK_ACTIVATE_URL` - Activation endpoint URL

**Options:**

| Flag                | Description                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `--product-id`      | DPP product ID. Will prompt if not provided.                       |
| `--name`            | Connection name. Will prompt if not provided.                      |
| `--description`     | Connection description.                                            |
| `--base-url`        | API base URL. Defaults to `DPP_BASE_URL`.                          |
| `--sso-url`         | SSO URL. Defaults to `DPP_SSO_URL`.                                |
| `--realm`           | OAuth2 realm ID. Defaults to `DPP_REALM`.                          |
| `--client-id`       | OAuth2 client ID. Defaults to `DPP_CLIENT_ID`.                     |
| `--username`        | OAuth2 username. Defaults to `DPP_USERNAME`.                       |
| `--password`        | OAuth2 password. Defaults to `DPP_PASSWORD`.                       |
| `--provider-type-id`| Provider type ID. Defaults to webhook_receive type.                |
| `--unit-field-id`   | Unit identifier field ID. Defaults to standard field.              |
| `--yes`             | Skip confirmation prompts.                                         |
| `--dry-run`         | Print request without sending.                                     |

**OAuth2 Credentials:**

When credentials are not found in `.env`, the command will interactively prompt for:

| Credential      | Environment Variable | Description                                    |
| --------------- | -------------------- | ---------------------------------------------- |
| SSO URL         | `DPP_SSO_URL`        | OAuth2 token endpoint base URL                 |
| Realm ID        | `DPP_REALM`          | Tenant/realm identifier                        |
| Client ID       | `DPP_CLIENT_ID`      | OAuth2 client ID (default: `client.frontend`)  |
| Username        | `DPP_USERNAME`       | User email for password grant                  |
| Password        | `DPP_PASSWORD`       | User password                                  |
| API Base URL    | `DPP_BASE_URL`       | DPP API base URL                               |

Credentials are saved to `.env` after first entry and reused for subsequent commands.

---

## connections

List all webhook connections for the authenticated user.

```bash
# List all connections
dpp-webhook connections

# With explicit credentials
dpp-webhook connections --username user@example.com --password pass
```

**Output:**

```
📋 Webhook Connections

  📡 Authenticating with DPP API...
  ✅ Authenticated successfully

  🔍 Fetching connections...

  Found 3 connection(s):

  ────────────────────────────────────────────────────────────────
  Name           : EV Battery Assembly Line – Webhook
  ID             : 01KV62G32NV20A9XK9R2ZJ9J0T
  State          : active
  Provider       : webhook_receive
  Created        : 2026-06-15T16:40:37

  ────────────────────────────────────────────────────────────────
  Name           : Cleantron Webhook - 02
  ID             : 01KV5XKC3C5P64TECDBJKE0H2C
  State          : active
  Provider       : webhook_receive
  Created        : 2026-06-15T15:15:02

  ────────────────────────────────────────────────────────────────
  Current        : 01KV62G32NV20A9XK9R2ZJ9J0T
```

**Options:**

| Flag          | Description                                    |
| ------------- | ---------------------------------------------- |
| `--base-url`  | API base URL. Defaults to `DPP_BASE_URL`.      |
| `--sso-url`   | SSO URL. Defaults to `DPP_SSO_URL`.            |
| `--realm`     | OAuth2 realm ID. Defaults to `DPP_REALM`.      |
| `--client-id` | OAuth2 client ID. Defaults to `DPP_CLIENT_ID`. |
| `--username`  | OAuth2 username. Defaults to `DPP_USERNAME`.   |
| `--password`  | OAuth2 password. Defaults to `DPP_PASSWORD`.   |

---

## health

Check health status of a webhook connection.

```bash
# Check current connection (from DPP_WEBHOOK_URL)
dpp-webhook health

# Check specific connection
dpp-webhook health --connection-id 01KV62G32NV20A9XK9R2ZJ9J0T
```

**Output:**

```
🏥 Connection Health Check

  📡 Authenticating with DPP API...
  ✅ Authenticated successfully

  🔍 Checking health for connection: 01KV62G32NV20A9XK9R2ZJ9J0T

  ────────────────────────────────────────────────────────────────
  State          : active
  Last Tested    : 2026-06-15T16:41:26
  Last Result    : N/A
  Last Used      : Never
  Test Failures  : 0
  Auth Failures  : 0

  ✅ Connection is healthy
```

**Options:**

| Flag              | Description                                              |
| ----------------- | -------------------------------------------------------- |
| `--connection-id` | Connection ID. Defaults to ID from `DPP_WEBHOOK_URL`.    |
| `--base-url`      | API base URL. Defaults to `DPP_BASE_URL`.                |
| `--sso-url`       | SSO URL. Defaults to `DPP_SSO_URL`.                      |
| `--realm`         | OAuth2 realm ID. Defaults to `DPP_REALM`.                |
| `--client-id`     | OAuth2 client ID. Defaults to `DPP_CLIENT_ID`.           |
| `--username`      | OAuth2 username. Defaults to `DPP_USERNAME`.             |
| `--password`      | OAuth2 password. Defaults to `DPP_PASSWORD`.             |

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

### initiate

Creates a DPP. Generates a serial automatically if `--serial` is omitted.

```bash
dpp-webhook initiate

# Or supply your own serial
dpp-webhook initiate --serial SN-XXXXXXXXXXXX
```

### activate

Publishes a initiated DPP by serial.

```bash
dpp-webhook activate --serial SN-XXXXXXXXXXXX
```

Uses `DPP_WEBHOOK_ACTIVATE_URL` or `DPP_ACTIVATE_URL` for the endpoint URL (falls back to `DPP_WEBHOOK_URL` if neither is set).

### update

BMS-like update on a published DPP.

```bash
dpp-webhook update --serial SN-XXXXXXXXXXXX
```

**Options (initiate / activate / update):**

| Flag        | Description                                                                             |
| ----------- | --------------------------------------------------------------------------------------- |
| `--serial`  | Serial number. If omitted, `initiate` generates one; `activate`/`update` prompt for it. |
| `--secret`  | Webhook secret. Defaults to `DPP_WEBHOOK_SECRET`.                                       |
| `--url`     | Endpoint URL. Defaults to `DPP_WEBHOOK_URL` (or activate URL for `activate`).           |
| `--payload` | Override default payload JSON file for the operation.                                   |
| `--dry-run` | Print signed request without sending.                                                   |
| `--timeout` | HTTP timeout in seconds. Defaults to `30`.                                              |

Each command prints the serial and the suggested next command on success.

---

## workflow

Runs the full initiate → update → activate pipeline for N DPPs in sequence. Pauses for confirmation between phases (skip with `--yes`). Prints a live summary table at the end.

**Interactive Connection Setup:**

When running `dpp-webhook workflow` with no connection configured, the command will:
1. Detect that no webhook connection is configured in `.env`
2. Ask if you want to create one now
3. If yes, run the full interactive connection setup:
   - Prompt for OAuth2 credentials (if not in `.env`)
   - Authenticate with DPP API
   - Show existing connections for selection, or create a new one
   - Save everything to `.env`
4. After setup, automatically proceed with the workflow

**Interactive Connection Selection:**

When running `dpp-webhook workflow`, the command will:
1. Show the current connection being used
2. List all available connections (if OAuth credentials are configured)
3. Allow selecting a different connection before starting
4. Update `.env` automatically if a different connection is selected

```bash
# 3 DPPs, interactive with connection selection
dpp-webhook workflow

# 5 DPPs, non-interactive (uses current connection)
dpp-webhook workflow --count 5 --yes

# Preview without sending
dpp-webhook workflow --dry-run --yes
```

**Example Flow — No Connection Configured:**

```
🔄 DPP Workflow  ·  3 DPP(s)  ·  initiate → update → activate

  ⚠️  No webhook connection configured.
  You need a connection to run the workflow.

  Create a new webhook connection now? [Y/n]: Y

  ⚠️  OAuth2 credentials not found in .env
  Missing: DPP_SSO_URL, DPP_REALM, DPP_USERNAME, DPP_PASSWORD

  🔐 OAuth2 Credentials Required
  SSO URL: https://cleantron-sso.digiprodpass.com
  Realm ID: 01KP7KHVPH6NSYC8ZDE6REEX8N
  Client ID [client.frontend]:
  Username: user@example.com
  Password: ********
  API Base URL: https://cleantron-api.digiprodpass.com/api

  📝 Saving OAuth credentials to .env...
  📡 Authenticating with DPP API...
  ✅ Authenticated successfully

  📋 Existing Connections:
  1. EV Battery Assembly Line – Webhook
     ID: 01KV62G32NV20A9XK9R2ZJ9J0T | State: active
  2. Cleantron Webhook - 02
     ID: 01KV5XKC3C5P64TECDBJKE0H2C | State: active

  0. Create new connection

  Select connection [0-2]: 0

  Do you want to create a new webhook connection? [Y/n]: Y
  Enter your DPP product ID: 01KQYD3G8PB93P4BRD4GFDWXC5
  Connection name (press Enter for auto-generated):

  🔗 Creating webhook connection...
  ✅ Connection created successfully!

  📝 Updated .env:
  DPP_WEBHOOK_ACTIVATE_URL: https://.../api/webhooks/dpps/01KV.../activate
  DPP_WEBHOOK_SECRET      : aiaQ457_6AsazMpkxrz_...
  DPP_WEBHOOK_URL         : https://.../api/webhooks/dpps/01KV...

  ✅ Connection ready!

  📡 Current Connection:
  Connection ID   : 01KVA5B3C4D5E6F7G8H9
  Webhook URL     : https://.../api/webhooks/dpps/01KVA5B3C4D5E6F7G8H9
  Activate URL    : https://.../api/webhooks/dpps/01KVA5B3C4D5E6F7G8H9/activate

  Webhook URL     : https://.../api/webhooks/dpps/01KVA5B3C4D5E6F7G8H9
  Activate URL    : https://.../api/webhooks/dpps/01KVA5B3C4D5E6F7G8H9/activate

  Start workflow? [Y/n]:
```

**Example Flow — Connection Already Configured:**

```
🔄 DPP Workflow  ·  3 DPP(s)  ·  initiate → update → activate

  📡 Current Connection:
  Connection ID   : 01KV62G32NV20A9XK9R2ZJ9J0T
  Webhook URL     : https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T
  Activate URL    : https://cleantron-api.digiprodpass.com/api/webhooks/dpps/01KV62G32NV20A9XK9R2ZJ9J0T/activate

  📋 Available Connections:
  1. EV Battery Assembly Line – Webhook ◀ current
     ID: 01KV62G32NV20A9XK9R2ZJ9J0T | State: active
  2. Cleantron Webhook - 02
     ID: 01KV5XKC3C5P64TECDBJKE0H2C | State: active
  3. Test Connection
     ID: 01KV5ZMH8BWNDNXW4Z8MNP372V | State: inactive

  0. Use current connection

  Select connection [0-3] (default: current):
```

**Options:**

| Flag             | Description                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| `--count`        | Number of DPPs to initiate. Defaults to `3`.                                |
| `--yes`          | Skip all confirmation prompts (uses current connection).                    |
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
