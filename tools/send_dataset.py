#!/usr/bin/env python3
"""Envia o dataset criptografado para a API do teste."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://localhost:8000/webhooks/grummer",
        help="URL completa do endpoint",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "webhook_payloads.json",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def response_status(raw: bytes) -> str:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_response"
    return str(value.get("status", "missing_status"))


def main() -> int:
    args = parse_args()
    records = json.loads(args.dataset.read_text(encoding="utf-8"))
    results: Counter[tuple[int | str, str]] = Counter()

    for index, record in enumerate(records, start=1):
        headers = {"Content-Type": "application/json", **record.get("headers", {})}
        request = Request(
            args.url,
            data=json.dumps(record["body"]).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=args.timeout) as response:
                body = response.read()
                code = response.status
        except HTTPError as error:
            body = error.read()
            code = error.code
        except URLError as error:
            print(f"Falha de conexão no item {index}: {error.reason}")
            return 2

        status = response_status(body)
        results[(code, status)] += 1
        print(f"{index:02d}/{len(records)} HTTP {code} {status}")

    print("\nResumo")
    for (code, status), count in sorted(results.items(), key=lambda item: str(item[0])):
        print(f"HTTP {code} {status}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
