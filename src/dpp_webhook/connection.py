"""Connection creation and OAuth2 authentication for DPP webhook setup.

This module handles:
- OAuth2 password grant token acquisition
- Webhook connection creation via the DPP API
- .env file management for storing connection credentials
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


# Default provider type for webhook_receive connections
DEFAULT_PROVIDER_TYPE_ID = "01KS593JNR3AG9ECWFV7Q0K8HH"

# Default unit identifier field ID (uniqueBatteryIdentifier path)
DEFAULT_UNIT_IDENTIFIER_FIELD_ID = "01KQWAPJFEVGK2F5SMDD3S1PGS"

# Static OAuth2 defaults (same for all Cleantron DPP tenants)
DEFAULT_SSO_URL = "https://cleantron-sso.digiprodpass.com"
DEFAULT_REALM = "01KP7KHVPH6NSYC8ZDE6REEX8N"
DEFAULT_CLIENT_ID = "client.frontend"
DEFAULT_CLIENT_SECRET = "EnUZPWT3lWbX86sXjN8Usg14WLFkTaZC"
DEFAULT_BASE_URL = "https://cleantron-api.digiprodpass.com"


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth2 password grant configuration."""
    sso_url: str
    realm: str
    client_id: str
    client_secret: str
    username: str
    password: str


@dataclass(frozen=True)
class ConnectionConfig:
    """Configuration for creating a webhook connection."""
    product_id: str
    name: str
    description: str
    provider_type_id: str
    unit_identifier_field_id: str


@dataclass(frozen=True)
class ConnectionResult:
    """Result from successful connection creation."""
    id: str
    webhook_secret: str
    endpoint_url: str
    unit_identifier_path: str
    name: str
    base_url: str

    @property
    def webhook_url(self) -> str:
        """Full webhook URL for data ingestion."""
        return f"{self.base_url}{self.endpoint_url}"

    @property
    def activate_url(self) -> str:
        """Full webhook URL for activation."""
        return f"{self.base_url}{self.endpoint_url}/activate"


class DppConnectionError(RuntimeError):
    """Raised when connection creation, authentication, or API calls fail."""
    pass


def _parse_error_body(exc: HTTPError) -> str:
    """Extract a human-readable message from an HTTP error response."""
    error_body = exc.read().decode("utf-8", errors="replace")
    try:
        error_data = json.loads(error_body)
        return error_data.get("message") or error_data.get("error_description") or error_body
    except (json.JSONDecodeError, ValueError):
        return error_body


def get_oauth_token(config: OAuthConfig) -> str:
    """Acquire an OAuth2 access token using password grant.

    Args:
        config: OAuth2 configuration with SSO URL, realm, credentials

    Returns:
        Access token string

    Raises:
        DppConnectionError: If authentication fails
    """
    token_url = (
        f"{config.sso_url}/realms/{config.realm}"
        f"/protocol/openid-connect/token"
    )

    body = urlencode({
        "grant_type": "password",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "username": config.username,
        "password": config.password,
    }).encode("utf-8")

    request = Request(
        url=token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["access_token"]
    except HTTPError as exc:
        detail = _parse_error_body(exc)
        raise DppConnectionError(
            f"OAuth2 authentication failed (HTTP {exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise DppConnectionError(
            f"OAuth2 authentication failed: {exc.reason}"
        ) from exc


def create_connection(
    base_url: str,
    token: str,
    config: ConnectionConfig,
) -> ConnectionResult:
    """Create a new webhook connection via the DPP API.

    Args:
        base_url: API base URL (e.g., https://cleantron-api.digiprodpass.com/api)
        token: OAuth2 bearer token
        config: Connection configuration

    Returns:
        ConnectionResult with connection ID, secret, and URLs

    Raises:
        DppConnectionError: If connection creation fails
    """
    url = f"{base_url}/api/connections"

    payload = {
        "name": config.name,
        "description": config.description,
        "providerTypeId": config.provider_type_id,
        "lifecycleState": "active",
        "config": {
            "productId": config.product_id,
            "unitIdentifierFieldId": config.unit_identifier_field_id,
            "defaultOperation": "upsert",
            "maxPayloadSizeBytes": 5524288,
            "signature": {
                "scheme": "hmac_sha256",
                "header": "X-DPP-Signature",
                "timestampHeader": "X-DPP-Timestamp",
                "replayWindowSeconds": 300,
            },
            "allowedSourceIps": None,
        },
    }

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    request = Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

            if data.get("status") != "success":
                raise DppConnectionError(
                    f"Connection creation failed: {data.get('message', 'Unknown error')}"
                )

            result = data["data"]
            return ConnectionResult(
                id=result["id"],
                webhook_secret=result["webhookSecret"],
                endpoint_url=result["endpointUrl"],
                unit_identifier_path=result["unitIdentifierPath"],
                name=result["name"],
                base_url=base_url,
            )
    except HTTPError as exc:
        detail = _parse_error_body(exc)
        raise DppConnectionError(
            f"Connection creation failed (HTTP {exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise DppConnectionError(
            f"Connection creation failed: {exc.reason}"
        ) from exc


def list_connections(
    base_url: str,
    token: str,
) -> list[dict[str, Any]]:
    """List all existing webhook connections.

    Args:
        base_url: API base URL
        token: OAuth2 bearer token

    Returns:
        List of connection dictionaries with id, name, lifecycleState, etc.

    Raises:
        DppConnectionError: If listing fails
    """
    url = f"{base_url}/api/connections"

    request = Request(
        url=url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

            if data.get("status") != "success":
                raise DppConnectionError(
                    f"Failed to list connections: {data.get('message', 'Unknown error')}"
                )

            return data.get("data", [])
    except HTTPError as exc:
        detail = _parse_error_body(exc)
        raise DppConnectionError(
            f"Failed to list connections (HTTP {exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise DppConnectionError(
            f"Failed to list connections: {exc.reason}"
        ) from exc


def get_connection_details(
    base_url: str,
    token: str,
    connection_id: str,
) -> dict[str, Any]:
    """Get details of a specific connection.

    Args:
        base_url: API base URL
        token: OAuth2 bearer token
        connection_id: Connection ID to retrieve

    Returns:
        Connection details dictionary (id, name, lifecycleState, etc.)

    Raises:
        DppConnectionError: If retrieval fails
    """
    url = f"{base_url}/api/connections/{connection_id}"

    request = Request(
        url=url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

            if data.get("status") != "success":
                raise DppConnectionError(
                    f"Failed to get connection: {data.get('message', 'Unknown error')}"
                )

            return data.get("data", {})
    except HTTPError as exc:
        detail = _parse_error_body(exc)
        raise DppConnectionError(
            f"Failed to get connection (HTTP {exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise DppConnectionError(
            f"Failed to get connection: {exc.reason}"
        ) from exc


def check_connection_health(
    base_url: str,
    token: str,
    connection_id: str,
) -> dict[str, Any]:
    """Check health status of a connection.

    Args:
        base_url: API base URL
        token: OAuth2 bearer token
        connection_id: Connection ID to check

    Returns:
        Health status dictionary with lifecycleState, lastTestResult, etc.

    Raises:
        DppConnectionError: If health check fails
    """
    url = f"{base_url}/api/connections/{connection_id}/health"

    request = Request(
        url=url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

            if data.get("status") != "success":
                raise DppConnectionError(
                    f"Health check failed: {data.get('message', 'Unknown error')}"
                )

            return data.get("data", {})
    except HTTPError as exc:
        detail = _parse_error_body(exc)
        raise DppConnectionError(
            f"Health check failed (HTTP {exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise DppConnectionError(
            f"Health check failed: {exc.reason}"
        ) from exc


def validate_oauth_credentials(config: OAuthConfig) -> bool:
    """Validate OAuth2 credentials by attempting to get a token.

    Args:
        config: OAuth2 configuration to validate

    Returns:
        True if credentials are valid

    Raises:
        DppConnectionError: If credentials are invalid
    """
    get_oauth_token(config)
    return True


def generate_connection_name() -> str:
    """Generate a default connection name with timestamp."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"DPP Webhook - {timestamp}"


def extract_connection_id_from_url(url: str) -> str:
    """Extract connection ID from a webhook URL, handling trailing slashes.

    Args:
        url: Webhook URL like https://.../webhooks/dpps/{ID} or .../dpps/{ID}/

    Returns:
        Connection ID string, or empty string if not found
    """
    if not url:
        return ""
    # Strip trailing slash before splitting
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else ""


def update_dotenv_file(
    path: Path,
    updates: dict[str, str],
) -> list[str]:
    """Update or add key-value pairs in a .env file.

    Preserves comments, formatting, and existing values not in updates.
    Does NOT override existing keys that are already set in the shell.

    Args:
        path: Path to .env file
        updates: Dictionary of KEY=VALUE pairs to update/add

    Returns:
        List of keys that were updated or added
    """
    import os

    lines: list[str] = []
    updated_keys: list[str] = []

    # Read existing file if it exists
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    # Track which keys we've seen
    seen_keys: set[str] = set()

    # Update existing lines
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "=" not in stripped:
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            # Only update if not already set in shell
            if key not in os.environ:
                lines[i] = f"{key}={updates[key]}"
                updated_keys.append(key)
            seen_keys.add(key)

    # Add new keys that weren't in the file
    for key, value in updates.items():
        if key not in seen_keys and key not in os.environ:
            lines.append(f"{key}={value}")
            updated_keys.append(key)

    # Write back to file
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return updated_keys
