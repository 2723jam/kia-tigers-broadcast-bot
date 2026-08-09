from __future__ import annotations

import argparse
import json
import os
import sys

import requests


TELEGRAM_API_BASE_URL = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 20


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Public HTTPS webhook URL")
    parser.add_argument("--secret", default="", help="Optional Telegram webhook secret")
    parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Ask Telegram to discard pending updates when setting the webhook",
    )
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is required.", file=sys.stderr)
        return 1

    payload: dict[str, str | bool] = {
        "url": args.url,
        "allowed_updates": json.dumps(["message"]),
        "drop_pending_updates": args.drop_pending_updates,
    }
    if args.secret:
        payload["secret_token"] = args.secret

    response = requests.post(
        f"{TELEGRAM_API_BASE_URL}/bot{token}/setWebhook",
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"ok": False, "description": response.text}

    print(json.dumps(body, ensure_ascii=False, indent=2))
    return 0 if response.ok and body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
