from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .client import WebhookClientError, post_signed_payload
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

    payload["messageId"] = args.message_id or str(uuid4())
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
    result = run_operation(
        "create",
        serial,
        secret=resolve_secret(args.secret),
        url=resolve_url(args.url),
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
    result = run_operation(
        "activate",
        serial,
        secret=resolve_secret(args.secret),
        url=resolve_activate_url(args.url),
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
    result = run_operation(
        "update",
        serial,
        secret=resolve_secret(args.secret),
        url=resolve_url(args.url),
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


def workflow_command(args: argparse.Namespace) -> int:
    secret = resolve_secret(args.secret)
    webhook_url = resolve_url(args.url)
    activate_url = resolve_activate_url(getattr(args, "activate_url", None))
    count = args.count

    if count < 1:
        raise ValueError("--count must be at least 1.")

    print(ui.phase_header(f"🔄 DPP Workflow  ·  {count} DPP(s)  ·  create → activate → update"))
    print(ui.lbl("Webhook URL", webhook_url))
    print(ui.lbl("Activate URL", activate_url))
    if args.dry_run:
        print(ui.lbl("Mode", ui.c("🔍 dry-run  (no requests will be sent)", ui.YELLOW, ui.BOLD)))

    if not confirm("\nStart workflow?", args.yes):
        print(ui.c("  🛑 Aborted.", ui.DIM))
        return 0

    serials: list[str] = []
    results: dict[str, dict[str, OperationResult]] = {}

    def record(result: OperationResult) -> None:
        results.setdefault(result.serial, {})[result.operation] = result

    print(ui.phase_header("📦 Phase 1  ▸  create"))
    for index in range(1, count + 1):
        serial = generate_serial()
        serials.append(serial)
        print(ui.item_header(index, count, "📦 Creating DPP"))
        try:
            result = run_operation_verbose(
                "create", serial,
                secret=secret, url=webhook_url,
                dry_run=args.dry_run, timeout_seconds=args.timeout,
            )
        except WebhookClientError:
            print(ui.err_line("Create failed. Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1
        record(result)
        if not result.ok:
            print(ui.err_line(f"Create failed (status {result.status}). Stopping workflow."))
            print(ui.summary_table(serials, results))
            return 1

    if not confirm("\nProceed to activate (publish) the created DPPs?", args.yes):
        print(ui.c("  🛑 Stopped after create.", ui.DIM))
        print(ui.summary_table(serials, results))
        return 0

    print(ui.phase_header("🚀 Phase 2  ▸  activate"))
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

    if not confirm("\nProceed to update (BMS update) the published DPPs?", args.yes):
        print(ui.c("  🛑 Stopped after activate.", ui.DIM))
        print(ui.summary_table(serials, results))
        return 0

    print(ui.phase_header("🔧 Phase 3  ▸  update (BMS)"))
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

    create = subparsers.add_parser("create", help="Create a DPP (upsert). Generates a serial if omitted.")
    add_operation_args(create, "create")
    create.set_defaults(handler=create_command)

    activate = subparsers.add_parser("activate", help="Publish/activate a DPP by serial (status_update).")
    add_operation_args(activate, "activate")
    activate.set_defaults(handler=activate_command)

    update = subparsers.add_parser("update", help="BMS-like update of a published DPP by serial (upsert).")
    add_operation_args(update, "update")
    update.set_defaults(handler=update_command)

    workflow = subparsers.add_parser(
        "workflow",
        help="Run create -> activate -> update for N DPPs end to end.",
    )
    workflow.add_argument("--count", type=int, default=3, help="Number of DPPs to create. Defaults to 3.")
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
