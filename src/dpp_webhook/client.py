from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .signing import SignedWebhookPayload, sign_payload


@dataclass(frozen=True)
class WebhookResponse:
    status: int
    body: str
    headers: dict[str, str]


class WebhookClientError(RuntimeError):
    pass


def send_signed_payload(
    url: str,
    payload: object,
    webhook_secret: str,
    timeout_seconds: float = 30,
) -> WebhookResponse:
    signed = sign_payload(payload, webhook_secret)
    return post_signed_payload(url, signed, timeout_seconds=timeout_seconds)


def post_signed_payload(
    url: str,
    signed: SignedWebhookPayload,
    timeout_seconds: float = 30,
) -> WebhookResponse:
    request = Request(
        url=url,
        data=signed.body.encode("utf-8"),
        headers=signed.headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return WebhookResponse(
                status=response.status,
                body=response_body,
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        detail = {
            "status": exc.code,
            "reason": exc.reason,
            "body": error_body,
        }
        raise WebhookClientError(json.dumps(detail, indent=2)) from exc
    except URLError as exc:
        raise WebhookClientError(str(exc.reason)) from exc
