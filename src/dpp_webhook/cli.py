from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import WebhookClientError, post_signed_payload
from .connection import (
    ConnectionConfig,
    ConnectionResult,
    DEFAULT_BASE_URL,
    DEFAULT_PROVIDER_TYPE_ID,
    DEFAULT_UNIT_IDENTIFIER_FIELD_ID,
    DppConnectionError,
    OAuthConfig,
    create_connection,
    extract_connection_id_from_url,
    generate_connection_name,
    get_oauth_token,
    list_connections,
    check_connection_health,
    update_dotenv_file,
    validate_oauth_credentials,
)
from .flows import (
    DEFAULT_PAYLOAD_PATHS,
    OperationResult,
    generate_serial,
    run_operation,
)
from .signing import sign_payload
from . import ui

DEFAULT_PAYLOAD_PATH = Path("examples/payload.json")


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ without overriding
    variables already set in the shell. No third-party dependency."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_payload(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def prepare_payload(args: argparse.Namespace) -> Any:
    payload = load_payload(args.payload)
    if not isinstance(payload, dict):
        raise ValueError("Payload root must be a JSON object.")

    if args.preserve_message_id:
        return payload

    from .signing import utc_timestamp_ms
    payload["messageId"] = args.message_id or str(uuid4())
    payload["timestamp"] = args.timestamp or utc_timestamp_ms()
    return payload


def resolve_secret(value: str | None) -> str:
    secret = value or os.getenv("DPP_WEBHOOK_SECRET")
    if not secret:
        raise ValueError("Webhook secret missing. Use --secret or DPP_WEBHOOK_SECRET.")
    return secret


def resolve_url(value: str | None) -> str:
    url = value or os.getenv("DPP_WEBHOOK_URL")
    if not url:
        raise ValueError("Webhook URL missing. Use --url or DPP_WEBHOOK_URL.")
    return url


def resolve_activate_url(value: str | None) -> str:
    url = (
        value
        or os.getenv("DPP_WEBHOOK_ACTIVATE_URL")
        or os.getenv("DPP_ACTIVATE_URL")
    )
    if not url:
        raise ValueError(
            "Activate URL missing. Use --url, DPP_WEBHOOK_ACTIVATE_URL, or DPP_ACTIVATE_URL."
        )
    return url


def prompt_for_serial() -> str:
    serial = input("Serial number: ").strip()
    if not serial:
        raise ValueError("A serial number is required.")
    return serial


def print_signed_payload(signed: object) -> None:
    print(ui.phase_header("🔐 Generate Signed Payload"))
    print(ui.lbl("X-DPP-Timestamp", signed.timestamp))
    print(ui.lbl("X-DPP-Signature", ui.c(signed.signature, ui.DIM)))
    body_label = ui.c(f"{'Body':<17}", ui.CYAN)
    print(f"  {body_label} :\n{ui.pretty_json(signed.body)}")


def generate_command(args: argparse.Namespace) -> int:
    payload = prepare_payload(args)
    signed = sign_payload(payload, resolve_secret(args.secret), timestamp=args.timestamp)
    print_signed_payload(signed)
    return 0


def send_command(args: argparse.Namespace) -> int:
    payload = prepare_payload(args)
    signed = sign_payload(payload, resolve_secret(args.secret), timestamp=args.timestamp)
    url = resolve_url(args.url)

    print(ui.phase_header("📤 Send Webhook"))
    print(ui.lbl("URL", url))
    print(ui.lbl("Content-Type", "application/json"))
    print(ui.lbl("X-DPP-Timestamp", signed.timestamp))
    print(ui.lbl("X-DPP-Signature", ui.c(signed.signature, ui.DIM)))
    print(ui.request_preview(signed.body))

    if args.dry_run:
        tag = ui.c("🔍 [dry-run]", ui.YELLOW, ui.BOLD)
        print(f"\n  {tag} POST {url}")
        return 0

    print(f"\n  {ui.c('📤 POST', ui.BOLD)} {url}")
    response = post_signed_payload(url, signed, timeout_seconds=args.timeout)
    print(ui.lbl("Response status", ui.status_str(response.status)))
    if response.body:
        print(ui.response_block(response.body))
    return 0


def print_operation_result(result: OperationResult) -> None:
    if result.dry_run:
        print(f"[dry-run] {result.operation} serial={result.serial}")
        print(f"messageId: {result.message_id}")
        print(result.body)
        return
    print(f"{result.operation} serial={result.serial} -> status {result.status}")
    if result.body:
        print(result.body)


def create_command(args: argparse.Namespace) -> int:
    serial = args.serial or generate_serial()

    # Show connection info
    url = resolve_url(args.url)
    print(ui.phase_header("📦 Initiate DPP"))
    print(f"  {ui.lbl('Webhook URL', url)}")
    print(f"  {ui.lbl('Serial', ui.c(serial, ui.BRIGHT_MAGENTA))}")

    result = run_operation(
        "initiate",
        serial,
        secret=resolve_secret(args.secret),
        url=url,
        payload_path=args.payload,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
    )
    print_operation_result(result)
    if result.ok:
        print(f"\nSerial: {result.serial}")
        print("Next:")
        print(f"  dpp-webhook activate --serial {result.serial}")
    return 0 if result.ok else 1


def activate_command(args: argparse.Namespace) -> int:
    serial = args.serial or prompt_for_serial()

    # Show connection info
    url = resolve_activate_url(args.url)
    print(ui.phase_header("🚀 Activate DPP"))
    print(f"  {ui.lbl('Activate URL', url)}")
    print(f"  {ui.lbl('Serial', ui.c(serial, ui.BRIGHT_MAGENTA))}")

    result = run_operation(
        "activate",
        serial,
        secret=resolve_secret(args.secret),
        url=url,
        payload_path=args.payload,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
    )
    print_operation_result(result)
    if result.ok:
        print("\nNext:")
        print(f"  dpp-webhook update --serial {result.serial}")
    return 0 if result.ok else 1


def update_command(args: argparse.Namespace) -> int:
    serial = args.serial or prompt_for_serial()

    # Show connection info
    url = resolve_url(args.url)
    print(ui.phase_header("🔧 Update DPP"))
    print(f"  {ui.lbl('Webhook URL', url)}")
    print(f"  {ui.lbl('Serial', ui.c(serial, ui.BRIGHT_MAGENTA))}")

    result = run_operation(
        "update",
        serial,
        secret=resolve_secret(args.secret),
        url=url,
        payload_path=args.payload,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
    )
    print_operation_result(result)
    return 0 if result.ok else 1


def _drain_stdin() -> None:
    """Discard input typed ahead of the prompt (e.g. a stray Enter buffered
    from a fast double key-press on the previous confirmation), so it can't
    silently satisfy the next confirm() call without the user actually
    seeing and answering that prompt."""
    if not sys.stdin.isatty():
        return
    try:
        import select

        while select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
    except (ImportError, OSError, ValueError):
        pass


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    _drain_stdin()
    answer = input(f"{prompt} [Y/n]: ").strip().lower()
    return answer in ("", "y", "yes")


def run_operation_verbose(
    operation: str,
    serial: str | None,
    *,
    secret: str,
    url: str,
    payload_path: Path | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 30,
) -> OperationResult:
    from .flows import (
        get_serial,
        prepare_payload as flows_prepare_payload,
    )

    path = payload_path or DEFAULT_PAYLOAD_PATHS[operation]
    print(ui.lbl("Payload file", str(path)))

    payload = flows_prepare_payload(path, serial)
    resolved_serial = get_serial(payload) or (serial or "")
    print(ui.lbl("Serial", ui.c(resolved_serial, ui.BRIGHT_MAGENTA, ui.BOLD)))
    print(ui.lbl("messageId", str(payload["messageId"])))
    print(ui.lbl("timestamp", str(payload["timestamp"])))

    signed = sign_payload(payload, secret)
    print(ui.lbl("X-DPP-Timestamp", signed.timestamp))
    print(ui.lbl("X-DPP-Signature", ui.c(signed.signature, ui.DIM)))
    print(ui.request_preview(signed.body))

    if dry_run:
        tag = ui.c("[dry-run]", ui.YELLOW, ui.BOLD)
        print(f"  {tag} POST {url}")
        return OperationResult(
            operation=operation,
            serial=resolved_serial,
            message_id=str(payload["messageId"]),
            status=None,
            body=signed.body,
            dry_run=True,
        )

    print(f"  {ui.c('POST', ui.BOLD)} {url}")
    try:
        response = post_signed_payload(url, signed, timeout_seconds=timeout_seconds)
        print(ui.lbl("Response status", ui.status_str(response.status)))
        if response.body:
            print(ui.response_block(response.body))
        return OperationResult(
            operation=operation,
            serial=resolved_serial,
            message_id=str(payload["messageId"]),
            status=response.status,
            body=response.body,
            dry_run=False,
        )
    except WebhookClientError as exc:
        print(ui.err_line(str(exc)))
        raise


def prompt_oauth_credentials() -> dict[str, str]:
    """Prompt user for OAuth2 credentials. Only username/password are needed;
    all other values (SSO URL, realm, client ID, base URL) are static defaults."""
    print(f"\n  {ui.c('🔐 Login Required', ui.BOLD, ui.BRIGHT_YELLOW)}")

    credentials = {}

    username = input(f"  Username (email): ").strip()
    if not username:
        raise ValueError("Username is required.")
    credentials["DPP_USERNAME"] = username

    password = input(f"  Password: ").strip()
    if not password:
        raise ValueError("Password is required.")
    credentials["DPP_PASSWORD"] = password

    return credentials


def resolve_oauth_config(args: argparse.Namespace) -> OAuthConfig:
    """Resolve OAuth2 configuration. Uses static defaults for SSO URL,
    realm, client ID, and base URL. Only username/password from env or prompt."""
    from .connection import (
        DEFAULT_SSO_URL, DEFAULT_REALM, DEFAULT_CLIENT_ID,
        DEFAULT_CLIENT_SECRET, DEFAULT_BASE_URL,
    )

    sso_url = args.sso_url or os.getenv("DPP_SSO_URL", DEFAULT_SSO_URL)
    realm = args.realm or os.getenv("DPP_REALM", DEFAULT_REALM)
    client_id = args.client_id or os.getenv("DPP_CLIENT_ID", DEFAULT_CLIENT_ID)
    client_secret = os.getenv("DPP_CLIENT_SECRET", DEFAULT_CLIENT_SECRET)
    username = args.username or os.getenv("DPP_USERNAME")
    password = args.password or os.getenv("DPP_PASSWORD")

    # Only username/password are required from user; everything else has defaults
    missing = []
    if not username:
        missing.append("username")
    if not password:
        missing.append("password")

    # If missing, prompt user interactively
    if missing:
        print(f"\n  ⚠️  {ui.c('Login credentials not found in .env', ui.YELLOW)}")
        print(f"  {ui.c('Missing:', ui.DIM)} {', '.join(missing)}")

        credentials = prompt_oauth_credentials()

        # Save to .env
        env_path = Path(".env")
        print(f"\n  📝 Saving credentials to .env...")
        updated_keys = update_dotenv_file(env_path, credentials)
        for key in updated_keys:
            value = credentials[key]
            display_value = "*" * len(value) if key == "DPP_PASSWORD" else value
            print(f"  {ui.lbl(key, ui.c(display_value, ui.BRIGHT_GREEN))}")

        # Update os.environ
        for key, value in credentials.items():
            os.environ[key] = value

        username = credentials["DPP_USERNAME"]
        password = credentials["DPP_PASSWORD"]

    return OAuthConfig(
        sso_url=sso_url,
        realm=realm,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
    )


def prompt_product_id() -> str:
    """Prompt user for product ID interactively."""
    product_id = input("\n  Enter your DPP product ID: ").strip()
    if not product_id:
        raise ValueError("Product ID is required.")
    return product_id


def prompt_connection_name() -> str:
    """Prompt user for connection name (optional)."""
    name = input("  Connection name (press Enter for auto-generated): ").strip()
    return name if name else generate_connection_name()


def select_connection(connections: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Let user select a connection from the list."""
    if not connections:
        return None

    print(f"\n  {ui.c('📋 Existing Connections:', ui.BOLD, ui.BRIGHT_BLUE)}")
    for i, conn in enumerate(connections, 1):
        name = conn.get("name", "Unknown")
        conn_id = conn.get("id", "Unknown")
        state = conn.get("lifecycleState", "unknown")
        created = conn.get("createdAt", "Unknown")[:19] if conn.get("createdAt") else "Unknown"

        # Color code by state
        if state == "active":
            state_color = ui.BRIGHT_GREEN
        elif state == "inactive":
            state_color = ui.YELLOW
        else:
            state_color = ui.DIM

        print(f"  {ui.c(str(i), ui.BOLD)}. {name}")
        print(f"     ID: {ui.c(conn_id, ui.DIM)}")
        print(f"     State: {ui.c(state, state_color)} | Created: {created}")

    print(f"\n  {ui.c('0', ui.BOLD)}. Create new connection")

    while True:
        choice = input(f"\n  Select connection [0-{len(connections)}]: ").strip()
        if not choice:
            continue
        try:
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(connections):
                return connections[idx - 1]
            print(ui.err_line(f"Invalid choice. Enter 0-{len(connections)}."))
        except ValueError:
            print(ui.err_line("Enter a number."))


def connect_command(args: argparse.Namespace) -> int:
    """Create a new webhook connection with interactive prompts."""
    print(ui.phase_header("🔗 DPP Webhook Connection Setup"))

    # Resolve OAuth config first
    try:
        oauth_config = resolve_oauth_config(args)
    except ValueError as exc:
        print(ui.err_line(str(exc)))
        return 1

    # Authenticate
    print(f"\n  📡 Authenticating with DPP API...")
    try:
        token = get_oauth_token(oauth_config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Authentication failed: {exc}"))
        return 1
    print(f"  ✅ Authenticated successfully")

    # Get base URL
    base_url = args.base_url or os.getenv("DPP_BASE_URL", DEFAULT_BASE_URL)
    if not base_url:
        print(ui.err_line("DPP_BASE_URL or --base-url is required."))
        return 1

    # List existing connections and let user select
    if not args.product_id and not args.yes:
        try:
            connections = list_connections(base_url, token)
            if connections:
                selected = select_connection(connections)
                if selected:
                    # User selected existing connection - use it
                    conn_id = selected["id"]
                    print(f"\n  ✅ {ui.c('Using existing connection', ui.BRIGHT_GREEN)}")
                    print(f"  {ui.lbl('Connection ID', ui.c(conn_id, ui.BRIGHT_MAGENTA, ui.BOLD))}")

                    # Get full details to retrieve webhook secret
                    # Note: webhookSecret is only returned on creation, not on GET
                    # So we'll need to use the connection ID and note that secret must be set manually
                    print(f"\n  ⚠️  {ui.c('Note:', ui.YELLOW)} Webhook secret is only available from connection creation.")
                    print(f"  Please set DPP_WEBHOOK_SECRET manually in .env if not already set.")

                    # Update .env with connection ID
                    env_path = Path(".env")
                    endpoint_url = f"/api/webhooks/dpps/{conn_id}"
                    updates = {
                        "DPP_WEBHOOK_URL": f"{base_url}{endpoint_url}",
                        "DPP_WEBHOOK_ACTIVATE_URL": f"{base_url}{endpoint_url}/activate",
                    }

                    try:
                        updated_keys = update_dotenv_file(env_path, updates)
                        # Update os.environ so changes take effect in current session
                        for key, value in updates.items():
                            os.environ[key] = value
                        if updated_keys:
                            print(f"\n  📝 Updated .env:")
                            for key in updated_keys:
                                print(f"  {ui.lbl(key, ui.c(updates[key], ui.BRIGHT_GREEN))}")
                    except Exception as exc:
                        print(ui.err_line(f"Failed to update .env: {exc}"))
                        return 1

                    print(f"\n  🚀 Next steps:")
                    print(f"     dpp-webhook initiate")
                    return 0
        except DppConnectionError as exc:
            print(ui.c(f"  ⚠️  Could not list connections: {exc}", ui.DIM))

    # Create new connection
    if not args.yes:
        answer = input("\n  Do you want to create a new webhook connection? [Y/n]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            print(ui.c("  🛑 Aborted.", ui.DIM))
            return 0

    # Get product ID from args or prompt
    product_id = args.product_id
    if not product_id:
        product_id = prompt_product_id()

    # Get connection name from args or prompt
    name = args.name
    if not name:
        name = prompt_connection_name()

    description = args.description or "Webhook connection created via DPP CLI"

    print(f"\n  {ui.lbl('Product ID', ui.c(product_id, ui.BRIGHT_MAGENTA))}")
    print(f"  {ui.lbl('Connection Name', name)}")

    config = ConnectionConfig(
        product_id=product_id,
        name=name,
        description=description,
        provider_type_id=args.provider_type_id or DEFAULT_PROVIDER_TYPE_ID,
        unit_identifier_field_id=args.unit_field_id or DEFAULT_UNIT_IDENTIFIER_FIELD_ID,
    )

    print(f"\n  🔗 Creating webhook connection...")
    try:
        result = create_connection(base_url, token, config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Connection creation failed: {exc}"))
        return 1

    # Print success
    print(f"\n  ✅ {ui.c('Connection created!', ui.BRIGHT_GREEN, ui.BOLD)}")
    print(f"  {ui.lbl('Connection ID', ui.c(result.id, ui.BRIGHT_MAGENTA, ui.BOLD))}")

    # ── Activate & verify ────────────────────────────────────────
    print(f"\n  🚀 Activating connection...")
    try:
        health = check_connection_health(base_url, token, result.id)
        state = health.get("lifecycleState", "unknown")
        if state == "active":
            print(f"  ✅ {ui.c('Connection is active', ui.BRIGHT_GREEN)}")
        else:
            print(f"  ⚠️  {ui.c(f'Connection state: {state}', ui.YELLOW)}")
    except DppConnectionError:
        print(f"  ⚠️  {ui.c('Could not verify activation status', ui.YELLOW)}")

    # Print connection details
    print(f"\n  {ui.c('📋 Connection Details:', ui.BOLD)}")
    print(f"  {ui.lbl('Webhook URL', result.webhook_url)}")
    print(f"  {ui.lbl('Activate URL', result.activate_url)}")
    print(f"  {ui.lbl('Secret', ui.c(result.webhook_secret[:20] + '...', ui.DIM))}")

    # Update .env file
    env_path = Path(".env")
    print(f"\n  📝 Updating .env file...")

    updates = {
        "DPP_WEBHOOK_URL": result.webhook_url,
        "DPP_WEBHOOK_SECRET": result.webhook_secret,
        "DPP_WEBHOOK_ACTIVATE_URL": result.activate_url,
    }

    try:
        updated_keys = update_dotenv_file(env_path, updates)
        # Update os.environ so changes take effect in current session
        for key, value in updates.items():
            os.environ[key] = value
        print(f"\n  📝 .env updated with:")
        for key in updated_keys:
            value = updates[key]
            display = value[:20] + "..." if "SECRET" in key else value
            print(f"  {ui.lbl(key, ui.c(display, ui.BRIGHT_GREEN))}")
    except Exception as exc:
        print(ui.err_line(f"Failed to update .env: {exc}"))
        return 1

    print(f"\n  ✅ {ui.c('.env file updated', ui.BRIGHT_GREEN)}")

    # Next steps
    print(f"\n  🚀 Next steps:")
    print(f"     dpp-webhook initiate")
    print(f"     dpp-webhook workflow --count 3")

    return 0


def connections_command(args: argparse.Namespace) -> int:
    """List all webhook connections."""
    print(ui.phase_header("📋 Webhook Connections"))

    # Resolve OAuth config
    try:
        oauth_config = resolve_oauth_config(args)
    except ValueError as exc:
        print(ui.err_line(str(exc)))
        return 1

    # Authenticate
    print(f"\n  📡 Authenticating with DPP API...")
    try:
        token = get_oauth_token(oauth_config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Authentication failed: {exc}"))
        return 1
    print(f"  ✅ Authenticated successfully")

    # Get base URL
    base_url = args.base_url or os.getenv("DPP_BASE_URL")
    if not base_url:
        print(ui.err_line("DPP_BASE_URL or --base-url is required."))
        return 1

    # List connections
    print(f"\n  🔍 Fetching connections...")
    try:
        connections = list_connections(base_url, token)
    except DppConnectionError as exc:
        print(ui.err_line(f"Failed to list connections: {exc}"))
        return 1

    if not connections:
        print(f"\n  {ui.c('No connections found.', ui.DIM)}")
        print(f"\n  Create one with: dpp-webhook connect")
        return 0

    print(f"\n  {ui.c(f'Found {len(connections)} connection(s):', ui.BOLD)}")

    # Display connections table
    for conn in connections:
        conn_id = conn.get("id", "Unknown")
        name = conn.get("name", "Unknown")
        state = conn.get("lifecycleState", "unknown")
        provider = conn.get("providerType", "unknown")
        created = conn.get("createdAt", "Unknown")[:19] if conn.get("createdAt") else "Unknown"

        # Color code by state
        if state == "active":
            state_color = ui.BRIGHT_GREEN
        elif state == "inactive":
            state_color = ui.YELLOW
        else:
            state_color = ui.DIM

        print(f"\n  {ui.c('─' * 60, ui.DIM)}")
        print(f"  {ui.lbl('Name', name)}")
        print(f"  {ui.lbl('ID', ui.c(conn_id, ui.BRIGHT_MAGENTA))}")
        print(f"  {ui.lbl('State', ui.c(state, state_color))}")
        print(f"  {ui.lbl('Provider', provider)}")
        print(f"  {ui.lbl('Created', created)}")

    # Show current connection from .env
    current_conn_id = extract_connection_id_from_url(
        os.getenv("DPP_WEBHOOK_URL", "")
    )
    if current_conn_id:
        print(f"\n  {ui.c('─' * 60, ui.DIM)}")
        print(f"  {ui.lbl('Current', ui.c(current_conn_id, ui.BRIGHT_CYAN))}")

    return 0


def health_command(args: argparse.Namespace) -> int:
    """Check health of a webhook connection."""
    print(ui.phase_header("🏥 Connection Health Check"))

    # Resolve OAuth config
    try:
        oauth_config = resolve_oauth_config(args)
    except ValueError as exc:
        print(ui.err_line(str(exc)))
        return 1

    # Authenticate
    print(f"\n  📡 Authenticating with DPP API...")
    try:
        token = get_oauth_token(oauth_config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Authentication failed: {exc}"))
        return 1
    print(f"  ✅ Authenticated successfully")

    # Get base URL
    base_url = args.base_url or os.getenv("DPP_BASE_URL")
    if not base_url:
        print(ui.err_line("DPP_BASE_URL or --base-url is required."))
        return 1

    # Get connection ID
    connection_id = args.connection_id
    if not connection_id:
        connection_id = extract_connection_id_from_url(
            os.getenv("DPP_WEBHOOK_URL", "")
        )
        if not connection_id:
            print(ui.err_line("Connection ID required. Use --connection-id or set DPP_WEBHOOK_URL."))
            return 1

    print(f"\n  🔍 Checking health for connection: {ui.c(connection_id, ui.BRIGHT_MAGENTA)}")

    # Check health
    try:
        health = check_connection_health(base_url, token, connection_id)
    except DppConnectionError as exc:
        print(ui.err_line(f"Health check failed: {exc}"))
        return 1

    # Display health status
    state = health.get("lifecycleState", "unknown")
    last_tested = health.get("lastTestedAt", "Never")
    last_result = health.get("lastTestResult", "N/A")
    last_used = health.get("lastUsedAt", "Never")
    test_failures = health.get("recentTestFailures", 0)
    auth_failures = health.get("recentAuthFailures", 0)

    # Color code by state
    if state == "active":
        state_color = ui.BRIGHT_GREEN
    elif state == "inactive":
        state_color = ui.YELLOW
    else:
        state_color = ui.DIM

    print(f"\n  {ui.c('─' * 60, ui.DIM)}")
    print(f"  {ui.lbl('State', ui.c(state, state_color))}")
    tested_display = last_tested[:19] if last_tested != 'Never' else 'Never'
    print(f"  {ui.lbl('Last Tested', tested_display)}")
    print(f"  {ui.lbl('Last Result', last_result)}")
    used_display = last_used[:19] if last_used != 'Never' else 'Never'
    print(f"  {ui.lbl('Last Used', used_display)}")
    print(f"  {ui.lbl('Test Failures', str(test_failures))}")
    print(f"  {ui.lbl('Auth Failures', str(auth_failures))}")

    # Health status
    if test_failures == 0 and auth_failures == 0:
        print(f"\n  ✅ {ui.c('Connection is healthy', ui.BRIGHT_GREEN, ui.BOLD)}")
    else:
        print(f"\n  ⚠️  {ui.c('Connection has issues', ui.YELLOW, ui.BOLD)}")

    return 0


def _run_connection_setup(skip_confirm: bool = False) -> bool:
    """Run the interactive connection setup flow.

    Args:
        skip_confirm: If True, skips the inner "Create new?" prompt
                      (caller already confirmed).

    Returns True if a connection was successfully created or selected,
    False if the user aborted or an error occurred.
    """
    # Resolve OAuth config (will prompt if missing)
    try:
        oauth_config = resolve_oauth_config(argparse.Namespace(
            sso_url=None, realm=None, client_id=None,
            username=None, password=None,
        ))
    except ValueError as exc:
        print(ui.err_line(str(exc)))
        return False

    # Authenticate
    print(f"\n  📡 Authenticating with DPP API...")
    try:
        token = get_oauth_token(oauth_config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Authentication failed: {exc}"))
        return False
    print(f"  ✅ Authenticated successfully")

    # Get base URL
    base_url = os.getenv("DPP_BASE_URL", DEFAULT_BASE_URL)
    if not base_url:
        print(ui.err_line("DPP_BASE_URL is required."))
        return False

    # List existing connections and let user select
    try:
        connections = list_connections(base_url, token)
        if connections:
            print(f"\n  {ui.c('📋 Existing Connections:', ui.BOLD, ui.BRIGHT_BLUE)}")
            for i, conn in enumerate(connections, 1):
                name = conn.get("name", "Unknown")
                conn_id = conn.get("id", "Unknown")
                state = conn.get("lifecycleState", "unknown")
                if state == "active":
                    state_color = ui.BRIGHT_GREEN
                elif state == "inactive":
                    state_color = ui.YELLOW
                else:
                    state_color = ui.DIM
                print(f"  {ui.c(str(i), ui.BOLD)}. {name}")
                print(f"     ID: {ui.c(conn_id, ui.DIM)} | State: {ui.c(state, state_color)}")

            print(f"\n  {ui.c('0', ui.BOLD)}. Create new connection")

            choice = input(f"\n  Select connection [0-{len(connections)}]: ").strip()
            if choice == "0" or not choice:
                pass  # Fall through to create new
            else:
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(connections):
                        selected = connections[idx - 1]
                        conn_id = selected["id"]
                        endpoint_url = f"/api/webhooks/dpps/{conn_id}"
                        updates = {
                            "DPP_WEBHOOK_URL": f"{base_url}{endpoint_url}",
                            "DPP_WEBHOOK_ACTIVATE_URL": f"{base_url}{endpoint_url}/activate",
                        }
                        env_path = Path(".env")
                        update_dotenv_file(env_path, updates)
                        for key, value in updates.items():
                            os.environ[key] = value

                        print(f"\n  ✅ {ui.c('Using connection', ui.BRIGHT_GREEN)}: {selected.get('name', 'Unknown')}")
                        print(f"  {ui.lbl('Connection ID', ui.c(conn_id, ui.BRIGHT_MAGENTA))}")
                        print(f"\n  ⚠️  {ui.c('Note:', ui.YELLOW)} Make sure DPP_WEBHOOK_SECRET is set in .env")
                        print(f"  (Set it manually if this is an existing connection.)")
                        return True
                except (ValueError, IndexError):
                    print(ui.c("  Invalid choice. Creating new connection.", ui.DIM))
    except DppConnectionError as exc:
        print(ui.c(f"  ⚠️  Could not list connections: {exc}", ui.DIM))

    # Create new connection (skip inner confirmation if caller already confirmed)
    if not skip_confirm:
        answer = input(f"\n  Do you want to create a new webhook connection? [Y/n]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            print(ui.c("  🛑 Aborted.", ui.DIM))
            return False

    product_id = input(f"\n  Enter your DPP product ID: ").strip()
    if not product_id:
        print(ui.err_line("Product ID is required."))
        return False

    name = input(f"  Connection name (press Enter for auto-generated): ").strip()
    if not name:
        name = generate_connection_name()

    print(f"\n  {ui.lbl('Product ID', ui.c(product_id, ui.BRIGHT_MAGENTA))}")
    print(f"  {ui.lbl('Connection Name', name)}")

    config = ConnectionConfig(
        product_id=product_id,
        name=name,
        description="Webhook connection created via DPP CLI",
        provider_type_id=DEFAULT_PROVIDER_TYPE_ID,
        unit_identifier_field_id=DEFAULT_UNIT_IDENTIFIER_FIELD_ID,
    )

    print(f"\n  🔗 Creating webhook connection...")
    try:
        result = create_connection(base_url, token, config)
    except DppConnectionError as exc:
        print(ui.err_line(f"Connection creation failed: {exc}"))
        return False

    print(f"\n  ✅ {ui.c('Connection created!', ui.BRIGHT_GREEN, ui.BOLD)}")
    print(f"  {ui.lbl('Connection ID', ui.c(result.id, ui.BRIGHT_MAGENTA, ui.BOLD))}")

    # ── Activate & verify ────────────────────────────────────────
    print(f"\n  🚀 Activating connection...")
    try:
        health = check_connection_health(base_url, token, result.id)
        state = health.get("lifecycleState", "unknown")
        if state == "active":
            print(f"  ✅ {ui.c('Connection is active', ui.BRIGHT_GREEN)}")
        else:
            print(f"  ⚠️  {ui.c(f'Connection state: {state}', ui.YELLOW)}")
    except DppConnectionError:
        print(f"  ⚠️  {ui.c('Could not verify activation status', ui.YELLOW)}")

    # ── Capture & save ───────────────────────────────────────────
    webhook_url = result.webhook_url
    webhook_secret = result.webhook_secret
    activate_url = result.activate_url

    print(f"\n  {ui.c('📋 Connection Details:', ui.BOLD)}")
    print(f"  {ui.lbl('Webhook URL', webhook_url)}")
    print(f"  {ui.lbl('Activate URL', activate_url)}")
    print(f"  {ui.lbl('Secret', ui.c(webhook_secret[:20] + '...', ui.DIM))}")

    # Update .env
    env_path = Path(".env")
    updates = {
        "DPP_WEBHOOK_URL": webhook_url,
        "DPP_WEBHOOK_SECRET": webhook_secret,
        "DPP_WEBHOOK_ACTIVATE_URL": activate_url,
    }

    try:
        update_dotenv_file(env_path, updates)
        for key, value in updates.items():
            os.environ[key] = value
        print(f"\n  📝 .env updated with:")
        for key in sorted(updates.keys()):
            value = updates[key]
            display = value[:20] + "..." if "SECRET" in key else value
            print(f"  {ui.lbl(key, ui.c(display, ui.BRIGHT_GREEN))}")
    except Exception as exc:
        print(ui.err_line(f"Failed to update .env: {exc}"))
        return False

    print(f"\n  ✅ {ui.c('Connection ready!', ui.BRIGHT_GREEN)}")
    return True


def _maybe_check_health(connection_id: str) -> None:
    """Check connection health if OAuth credentials are available, warn on issues."""
    base_url = os.getenv("DPP_BASE_URL", DEFAULT_BASE_URL)
    sso_url = os.getenv("DPP_SSO_URL", "https://cleantron-sso.digiprodpass.com")
    realm = os.getenv("DPP_REALM", "01KP7KHVPH6NSYC8ZDE6REEX8N")
    username = os.getenv("DPP_USERNAME", "")
    password = os.getenv("DPP_PASSWORD", "")

    if not all([base_url, sso_url, realm, username, password]):
        return  # Skip health check if OAuth not configured

    try:
        oauth_config = OAuthConfig(
            sso_url=sso_url, realm=realm,
            client_id=os.getenv("DPP_CLIENT_ID", "client.frontend"),
            client_secret=os.getenv("DPP_CLIENT_SECRET", "EnUZPWT3lWbX86sXjN8Usg14WLFkTaZC"),
            username=username, password=password,
        )
        token = get_oauth_token(oauth_config)
        health = check_connection_health(base_url, token, connection_id)

        state = health.get("lifecycleState", "unknown")
        test_failures = health.get("recentTestFailures", 0)
        auth_failures = health.get("recentAuthFailures", 0)

        if state == "active" and test_failures == 0 and auth_failures == 0:
            print(f"  {ui.lbl('Health', ui.c('✅ healthy', ui.BRIGHT_GREEN))}")
        elif state == "active":
            print(f"  {ui.lbl('Health', ui.c(f'⚠️ active but {test_failures} test / {auth_failures} auth failures', ui.YELLOW))}")
        else:
            print(f"  {ui.lbl('Health', ui.c(f'⚠️ {state}', ui.YELLOW, ui.BOLD))}")
            print(f"  {ui.c('  Connection may not be functional. Proceed with caution.', ui.YELLOW)}")
    except (DppConnectionError, Exception):
        pass  # Silently skip health check on error


def _prompt_connection_choice(current_conn_id: str) -> bool | None:
    """Present connection management options to the user.

    Returns:
        True  — user changed the connection (URLs updated in .env + os.environ)
        False — user aborted (should exit)
        None  — user chose to keep current connection
    """
    has_current = bool(current_conn_id)

    # Check if OAuth credentials are available for listing connections
    sso_url = os.getenv("DPP_SSO_URL", "https://cleantron-sso.digiprodpass.com")
    realm = os.getenv("DPP_REALM", "01KP7KHVPH6NSYC8ZDE6REEX8N")
    username = os.getenv("DPP_USERNAME", "")
    password = os.getenv("DPP_PASSWORD", "")
    base_url = os.getenv("DPP_BASE_URL", DEFAULT_BASE_URL)
    has_oauth = all([sso_url, realm, username, password, base_url])

    # Build options
    options = []
    if has_current:
        options.append(("use", "Use current connection"))
    if has_oauth:
        options.append(("select", "Select from existing connections"))
    options.append(("create", "Create new connection"))
    options.append(("quit", "Quit"))

    print(f"\n  {ui.c('🔌 Connection', ui.BOLD, ui.BRIGHT_BLUE)}")
    for i, (key, label) in enumerate(options, 1):
        print(f"  {ui.c(str(i), ui.BOLD)}. {label}")

    choice = input(f"\n  Choose [1-{len(options)}]: ").strip()
    if not choice:
        return None  # Default: keep current (or abort if no current)

    try:
        idx = int(choice)
    except ValueError:
        return None

    key = options[idx - 1][0] if 1 <= idx <= len(options) else None

    if key == "use":
        print(f"  ✅ {ui.c('Using current connection.', ui.BRIGHT_GREEN)}")
        return None

    if key == "quit":
        print(ui.c("  🛑 Aborted.", ui.DIM))
        return False

    if key == "create":
        print(f"\n  {ui.c('🔗 Creating new connection...', ui.BOLD)}")
        if not _run_connection_setup(skip_confirm=True):
            return False
        return True

    if key == "select":
        # Authenticate and list connections
        try:
            oauth_config = OAuthConfig(
                sso_url=sso_url, realm=realm,
                client_id=os.getenv("DPP_CLIENT_ID", "client.frontend"),
                client_secret=os.getenv("DPP_CLIENT_SECRET", "EnUZPWT3lWbX86sXjN8Usg14WLFkTaZC"),
                username=username, password=password,
            )
            token = get_oauth_token(oauth_config)
            connections = list_connections(base_url, token)
        except DppConnectionError as exc:
            print(ui.err_line(f"Failed to fetch connections: {exc}"))
            return None

        if not connections:
            print(f"\n  {ui.c('No existing connections found.', ui.DIM)}")
            return None

        print(f"\n  {ui.c('📋 Available Connections:', ui.BOLD, ui.BRIGHT_BLUE)}")
        for i, conn in enumerate(connections, 1):
            name = conn.get("name", "Unknown")
            conn_id = conn.get("id", "Unknown")
            state = conn.get("lifecycleState", "unknown")
            state_color = ui.BRIGHT_GREEN if state == "active" else (ui.YELLOW if state == "inactive" else ui.DIM)
            is_current = conn_id == current_conn_id
            marker = " ◀ current" if is_current else ""
            print(f"  {ui.c(str(i), ui.BOLD)}. {name}{ui.c(marker, ui.BRIGHT_CYAN if is_current else ui.DIM)}")
            print(f"     ID: {ui.c(conn_id, ui.DIM)} | State: {ui.c(state, state_color)}")

        choice = input(f"\n  Select connection [1-{len(connections)}, 0=cancel]: ").strip()
        if not choice or choice == "0":
            return None

        try:
            idx = int(choice)
            if 1 <= idx <= len(connections):
                selected = connections[idx - 1]
                conn_id = selected["id"]
                endpoint_url = f"/api/webhooks/dpps/{conn_id}"
                updates = {
                    "DPP_WEBHOOK_URL": f"{base_url}{endpoint_url}",
                    "DPP_WEBHOOK_ACTIVATE_URL": f"{base_url}{endpoint_url}/activate",
                }
                env_path = Path(".env")
                update_dotenv_file(env_path, updates)
                for k, v in updates.items():
                    os.environ[k] = v

                print(f"\n  ✅ {ui.c('Switched to', ui.BRIGHT_GREEN)}: {selected.get('name', 'Unknown')}")
                print(f"  {ui.lbl('Connection ID', ui.c(conn_id, ui.BRIGHT_MAGENTA))}")
                print(f"\n  ⚠️  {ui.c('Note:', ui.YELLOW)} Ensure DPP_WEBHOOK_SECRET is correct for this connection.")
                return True
        except (ValueError, IndexError):
            pass

        return None

    return None


def workflow_command(args: argparse.Namespace) -> int:
    count = args.count

    if count < 1:
        raise ValueError("--count must be at least 1.")
    if count > 1000:
        raise ValueError("--count cannot exceed 1000. For larger batches, use multiple runs.")

    print(ui.phase_header(f"🔄 DPP Workflow  ·  {count} DPP(s)  ·  initiate → update → activate"))

    # ── Connection check ──────────────────────────────────────────
    # Try to resolve connection config; if missing, offer to create one.
    try:
        secret = resolve_secret(args.secret)
        webhook_url = resolve_url(args.url)
        activate_url = resolve_activate_url(getattr(args, "activate_url", None))
    except ValueError as exc:
        if args.yes or args.dry_run:
            print(ui.err_line(str(exc)))
            return 1

        print(f"\n  ⚠️  {ui.c('No webhook connection configured.', ui.YELLOW)}")
        print(f"  {ui.c('You need a connection to run the workflow.', ui.DIM)}")

        answer = input(f"\n  Create a new webhook connection now? [Y/n]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            print(ui.c("  🛑 Aborted. Run 'dpp-webhook connect' first.", ui.DIM))
            return 1

        # ── Connection setup ───────────────────────────────────────
        if not _run_connection_setup(skip_confirm=True):
            return 1

        # Re-read .env to pick up new values
        load_dotenv()

        # Now re-resolve; if still missing, something went wrong
        try:
            secret = resolve_secret(args.secret)
            webhook_url = resolve_url(args.url)
            activate_url = resolve_activate_url(getattr(args, "activate_url", None))
        except ValueError as exc:
            print(ui.err_line(f"Connection setup did not complete: {exc}"))
            return 1

    # ── Show current connection ───────────────────────────────────
    # Show current connection info
    current_url = os.getenv("DPP_WEBHOOK_URL", "")
    current_conn_id = extract_connection_id_from_url(current_url)
    if current_conn_id:
        print(f"\n  {ui.c('📡 Current Connection:', ui.BOLD)}")
        print(f"  {ui.lbl('Connection ID', ui.c(current_conn_id, ui.BRIGHT_MAGENTA))}")

    # ── Health check ──────────────────────────────────────────────
    if not args.dry_run and current_conn_id:
        _maybe_check_health(current_conn_id)

    # ── Connection selection ──────────────────────────────────────
    # Always offer connection management as the first interactive step.
    if not args.yes and not args.dry_run:
        changed = _prompt_connection_choice(current_conn_id)
        if changed is False:  # User aborted
            return 1
        if changed:  # Connection was changed, re-resolve
            load_dotenv()
            try:
                secret = resolve_secret(args.secret)
                webhook_url = resolve_url(args.url)
                activate_url = resolve_activate_url(getattr(args, "activate_url", None))
            except ValueError as exc:
                print(ui.err_line(f"Connection setup did not complete: {exc}"))
                return 1
            current_conn_id = extract_connection_id_from_url(
                os.getenv("DPP_WEBHOOK_URL", "")
            )

    print(f"\n  {ui.lbl('Webhook URL', webhook_url)}")
    print(f"  {ui.lbl('Activate URL', activate_url)}")
    if args.dry_run:
        print(ui.lbl("Mode", ui.c("🔍 dry-run  (no requests will be sent)", ui.YELLOW, ui.BOLD)))

    if not confirm("\nStart workflow?", args.yes):
        print(ui.c("  🛑 Aborted.", ui.DIM))
        return 0

    serials: list[str] = []
    results: dict[str, dict[str, OperationResult]] = {}

    def record(result: OperationResult) -> None:
        results.setdefault(result.serial, {})[result.operation] = result

    print(ui.phase_header("📦 Phase 1  ▸  initiate"))
    for index in range(1, count + 1):
        serial = generate_serial()
        serials.append(serial)
        print(ui.item_header(index, count, "📦 Creating DPP"))
        try:
            result = run_operation_verbose(
                "initiate", serial,
                secret=secret, url=webhook_url,
                dry_run=args.dry_run, timeout_seconds=args.timeout,
            )
        except WebhookClientError:
            print(ui.err_line("Initiate failed. Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1
        record(result)
        if not result.ok:
            print(ui.err_line(f"Initiate failed (status {result.status}). Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1

    if not confirm("\nProceed to update (BMS update) the initiated DPPs?", args.yes):
        print(ui.c("  🛑 Stopped after initiate.", ui.DIM))
        print(ui.summary_table(serials, results))
        return 0

    print(ui.phase_header("🔧 Phase 2  ▸  update (BMS)"))
    for index, serial in enumerate(serials, start=1):
        print(ui.item_header(index, count, f"🔧 Updating DPP  serial={ui.c(serial, ui.BRIGHT_MAGENTA)}"))
        try:
            result = run_operation_verbose(
                "update", serial,
                secret=secret, url=webhook_url,
                dry_run=args.dry_run, timeout_seconds=args.timeout,
            )
        except WebhookClientError:
            print(ui.err_line("Update failed. Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1
        record(result)
        if not result.ok:
            print(ui.err_line(f"Update failed (status {result.status}). Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1

    if not confirm("\nProceed to activate (publish) the updated DPPs?", args.yes):
        print(ui.c("  🛑 Stopped after update.", ui.DIM))
        print(ui.summary_table(serials, results))
        return 0

    print(ui.phase_header("🚀 Phase 3  ▸  activate"))
    for index, serial in enumerate(serials, start=1):
        print(ui.item_header(index, count, f"🚀 Activating DPP  serial={ui.c(serial, ui.BRIGHT_MAGENTA)}"))
        try:
            result = run_operation_verbose(
                "activate", serial,
                secret=secret, url=activate_url,
                dry_run=args.dry_run, timeout_seconds=args.timeout,
            )
        except WebhookClientError:
            print(ui.err_line("Activate failed. Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1
        record(result)
        if not result.ok:
            print(ui.err_line(f"Activate failed (status {result.status}). Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1

    print(ui.summary_table(serials, results))
    return 0


def print_summary(
    serials: list[str],
    results: dict[str, dict[str, OperationResult]],
) -> None:
    print(ui.summary_table(serials, results))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dpp-webhook",
        description="Generate and send signed DPP webhook payloads.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Print signed headers and body.")
    add_common_args(generate)
    generate.set_defaults(handler=generate_command)

    send = subparsers.add_parser("send", help="Send signed payload to webhook URL.")
    add_common_args(send)
    send.add_argument("--url", help="Webhook ingestion URL. Defaults to DPP_WEBHOOK_URL.")
    send.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds.")
    send.add_argument("--dry-run", action="store_true", help="Print request without sending.")
    send.set_defaults(handler=send_command)

    create = subparsers.add_parser("initiate", help="Initiate a DPP (upsert). Generates a serial if omitted.")
    add_operation_args(create, "initiate")
    create.set_defaults(handler=create_command)

    activate = subparsers.add_parser("activate", help="Publish/activate a DPP by serial (status_update).")
    add_operation_args(activate, "activate")
    activate.set_defaults(handler=activate_command)

    update = subparsers.add_parser("update", help="BMS-like update of a published DPP by serial (upsert).")
    add_operation_args(update, "update")
    update.set_defaults(handler=update_command)

    connect = subparsers.add_parser(
        "connect",
        help="Create a new webhook connection with interactive setup.",
    )
    connect.add_argument(
        "--product-id",
        help="DPP product ID. Will prompt if not provided.",
    )
    connect.add_argument(
        "--name",
        help="Connection name. Will prompt if not provided.",
    )
    connect.add_argument(
        "--description",
        help="Connection description.",
    )
    connect.add_argument(
        "--base-url",
        help="API base URL. Defaults to DPP_BASE_URL.",
    )
    connect.add_argument(
        "--sso-url",
        help="SSO URL. Defaults to DPP_SSO_URL.",
    )
    connect.add_argument(
        "--realm",
        help="OAuth2 realm ID. Defaults to DPP_REALM.",
    )
    connect.add_argument(
        "--client-id",
        help="OAuth2 client ID. Defaults to DPP_CLIENT_ID.",
    )
    connect.add_argument(
        "--username",
        help="OAuth2 username. Defaults to DPP_USERNAME.",
    )
    connect.add_argument(
        "--password",
        help="OAuth2 password. Defaults to DPP_PASSWORD.",
    )
    connect.add_argument(
        "--provider-type-id",
        help=f"Provider type ID. Defaults to {DEFAULT_PROVIDER_TYPE_ID}.",
    )
    connect.add_argument(
        "--unit-field-id",
        help=f"Unit identifier field ID. Defaults to {DEFAULT_UNIT_IDENTIFIER_FIELD_ID}.",
    )
    connect.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts.",
    )
    connect.add_argument(
        "--dry-run",
        action="store_true",
        help="Print request without sending.",
    )
    connect.set_defaults(handler=connect_command)

    connections = subparsers.add_parser(
        "connections",
        help="List all webhook connections.",
    )
    connections.add_argument(
        "--base-url",
        help="API base URL. Defaults to DPP_BASE_URL.",
    )
    connections.add_argument(
        "--sso-url",
        help="SSO URL. Defaults to DPP_SSO_URL.",
    )
    connections.add_argument(
        "--realm",
        help="OAuth2 realm ID. Defaults to DPP_REALM.",
    )
    connections.add_argument(
        "--client-id",
        help="OAuth2 client ID. Defaults to DPP_CLIENT_ID.",
    )
    connections.add_argument(
        "--username",
        help="OAuth2 username. Defaults to DPP_USERNAME.",
    )
    connections.add_argument(
        "--password",
        help="OAuth2 password. Defaults to DPP_PASSWORD.",
    )
    connections.set_defaults(handler=connections_command)

    health = subparsers.add_parser(
        "health",
        help="Check health of a webhook connection.",
    )
    health.add_argument(
        "--connection-id",
        help="Connection ID. Defaults to ID from DPP_WEBHOOK_URL.",
    )
    health.add_argument(
        "--base-url",
        help="API base URL. Defaults to DPP_BASE_URL.",
    )
    health.add_argument(
        "--sso-url",
        help="SSO URL. Defaults to DPP_SSO_URL.",
    )
    health.add_argument(
        "--realm",
        help="OAuth2 realm ID. Defaults to DPP_REALM.",
    )
    health.add_argument(
        "--client-id",
        help="OAuth2 client ID. Defaults to DPP_CLIENT_ID.",
    )
    health.add_argument(
        "--username",
        help="OAuth2 username. Defaults to DPP_USERNAME.",
    )
    health.add_argument(
        "--password",
        help="OAuth2 password. Defaults to DPP_PASSWORD.",
    )
    health.set_defaults(handler=health_command)

    workflow = subparsers.add_parser(
        "workflow",
        help="Run initiate -> update -> activate for N DPPs end to end.",
    )
    workflow.add_argument("--count", type=int, default=3, help="Number of DPPs to initiate. Defaults to 3.")
    workflow.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")
    workflow.add_argument("--secret", help="Webhook secret. Defaults to DPP_WEBHOOK_SECRET.")
    workflow.add_argument("--url", help="Webhook ingestion URL. Defaults to DPP_WEBHOOK_URL.")
    workflow.add_argument(
        "--activate-url",
        help="Activate URL. Defaults to DPP_WEBHOOK_ACTIVATE_URL or DPP_ACTIVATE_URL.",
    )
    workflow.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds.")
    workflow.add_argument("--dry-run", action="store_true", help="Print requests without sending.")
    workflow.set_defaults(handler=workflow_command)

    return parser


def add_operation_args(parser: argparse.ArgumentParser, operation: str) -> None:
    parser.add_argument("--serial", help="Serial number (unit identifier).")
    parser.add_argument(
        "--payload",
        type=Path,
        help=f"Payload JSON file. Defaults to {DEFAULT_PAYLOAD_PATHS[operation]}.",
    )
    parser.add_argument("--secret", help="Webhook secret. Defaults to DPP_WEBHOOK_SECRET.")
    url_help = (
        "Activate URL. Defaults to DPP_ACTIVATE_URL or DPP_WEBHOOK_URL."
        if operation == "activate"
        else "Webhook ingestion URL. Defaults to DPP_WEBHOOK_URL."
    )
    parser.add_argument("--url", help=url_help)
    parser.add_argument("--timeout", type=float, default=30, help="HTTP timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Print request without sending.")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--payload",
        type=Path,
        default=DEFAULT_PAYLOAD_PATH,
        help=f"Payload JSON file. Defaults to {DEFAULT_PAYLOAD_PATH}.",
    )
    parser.add_argument(
        "--secret",
        help="Webhook secret. Defaults to DPP_WEBHOOK_SECRET.",
    )
    parser.add_argument(
        "--timestamp",
        help="Override X-DPP-Timestamp. Defaults to current UTC timestamp.",
    )
    parser.add_argument(
        "--message-id",
        help="Override payload messageId. Defaults to generated UUID per run.",
    )
    parser.add_argument(
        "--preserve-message-id",
        action="store_true",
        help="Keep messageId from payload file instead of generating one.",
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, WebhookClientError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
