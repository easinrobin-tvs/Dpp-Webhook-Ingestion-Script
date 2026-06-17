from __future__ import annotations

import json
import os
import sys

RESET          = "\033[0m"
BOLD           = "\033[1m"
DIM            = "\033[2m"
RED            = "\033[31m"
GREEN          = "\033[32m"
YELLOW         = "\033[33m"
BLUE           = "\033[34m"
MAGENTA        = "\033[35m"
CYAN           = "\033[36m"
BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"

_BAR_WIDTH = 64


def _colors() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, *codes: str) -> str:
    if not _colors():
        return text
    return "".join(codes) + text + RESET


def lbl(key: str, value: str, width: int = 17) -> str:
    padded = f"{key:<{width}}"
    return f"  {c(padded, CYAN)} : {value}"


def phase_header(title: str) -> str:
    bar = "━" * _BAR_WIDTH
    return f"\n{c(bar, BLUE)}\n  {c(title, BOLD, BRIGHT_BLUE)}\n{c(bar, BLUE)}"


def item_header(index: int, total: int, label: str) -> str:
    return f"\n{c('▶', BRIGHT_CYAN)} {c(f'[{index}/{total}]', DIM)} {c(label, BOLD)}"


def status_str(code: int | None, dry_run: bool = False) -> str:
    if dry_run:
        return c("dry-run", YELLOW, BOLD)
    if code is None:
        return c("—", DIM)
    raw = str(code)
    if 200 <= code < 300:
        return c(raw, BRIGHT_GREEN, BOLD)
    if 400 <= code < 500:
        return c(raw, BRIGHT_YELLOW, BOLD)
    return c(raw, BRIGHT_RED, BOLD)


def _colorize_json_value(val: str) -> str:
    stripped = val.strip().rstrip(",")
    if stripped in ("true", "false", "null"):
        return val.replace(stripped, c(stripped, MAGENTA), 1)
    try:
        float(stripped)
        return val.replace(stripped, c(stripped, BRIGHT_YELLOW), 1)
    except ValueError:
        pass
    if stripped.startswith('"'):
        return c(val, BRIGHT_GREEN)
    return val


def pretty_json(raw: str, prefix: str = "    ", max_lines: int = 0) -> str:
    try:
        parsed = json.loads(raw)
        text = json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        text = raw

    lines = text.splitlines()
    truncated = False
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    if _colors():
        out = []
        for line in lines:
            stripped = line.lstrip()
            indent = " " * (len(line) - len(stripped))
            if stripped.startswith('"') and '":' in stripped:
                colon = stripped.index('":')
                key_part = stripped[: colon + 2]
                val_part = stripped[colon + 2 :]
                out.append(indent + c(key_part, CYAN) + _colorize_json_value(val_part))
            elif stripped in ("{", "}", "[", "]", "{,", "},", "[,", "],"):
                out.append(indent + c(stripped, DIM))
            else:
                out.append(line)
        lines = out

    result = "\n".join(prefix + line for line in lines)
    if truncated:
        result += f"\n{prefix}{c('… (truncated)', DIM)}"
    return result


def response_block(raw: str) -> str:
    if not raw or not raw.strip():
        return f"  {c('(empty response body)', DIM)}"
    label_part = c("Response body", CYAN)
    return f"  {label_part:<{17 + (9 if _colors() else 0)}} :\n{pretty_json(raw)}"


def request_preview(raw: str, max_chars: int = 180) -> str:
    if len(raw) <= max_chars:
        preview, suffix = raw, ""
    else:
        preview, suffix = raw[:max_chars], c(" …", DIM)
    padded = f"{'Body preview':<17}"
    return f"  {c(padded, CYAN)} : {preview}{suffix}"


def ok_line(msg: str) -> str:
    return c(f"  ✅ {msg}", BRIGHT_GREEN)


def err_line(msg: str) -> str:
    return c(f"  ❌ {msg}", BRIGHT_RED)


def _table_cell(result: object, width: int) -> str:
    if result is None:
        return c("—".ljust(width), DIM)
    dry = getattr(result, "dry_run", False)
    status = getattr(result, "status", None)
    if dry:
        return c("dry-run".ljust(width), YELLOW, BOLD)
    if status is None:
        return c("—".ljust(width), DIM)
    raw = str(status)
    padded = raw.ljust(width)
    if 200 <= status < 300:
        return c(padded, BRIGHT_GREEN, BOLD)
    if 400 <= status < 500:
        return c(padded, BRIGHT_YELLOW, BOLD)
    return c(padded, BRIGHT_RED, BOLD)


def summary_table(
    serials: list[str],
    results: dict[str, dict[str, object]],
) -> str:
    S, O = 22, 12
    top = f"╔{'═' * S}╦{'═' * O}╦{'═' * O}╦{'═' * O}╗"
    hdr = f"║{'Serial':<{S}}║{'Initiate':<{O}}║{'Update':<{O}}║{'Activate':<{O}}║"
    mid = f"╠{'═' * S}╬{'═' * O}╬{'═' * O}╬{'═' * O}╣"
    bot = f"╚{'═' * S}╩{'═' * O}╩{'═' * O}╩{'═' * O}╝"

    lines = [
        "",
        f"  {c('📊 Summary', BOLD, BRIGHT_BLUE)}",
        c(top, BLUE),
        c(hdr, BOLD),
        c(mid, BLUE),
    ]
    for serial in serials:
        ops = results.get(serial, {})
        s = serial[:S].ljust(S)
        row = (
            f"║{s}║"
            f"{_table_cell(ops.get('initiate'), O)}║"
            f"{_table_cell(ops.get('update'), O)}║"
            f"{_table_cell(ops.get('activate'), O)}║"
        )
        lines.append(row)
    lines.append(c(bot, BLUE))
    return "\n".join(lines)
