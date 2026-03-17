"""Create a Daily.co webhook and output the webhook secret for env configuration.

Modes:
1) Let Daily generate secret (default): do not pass --hmac-base64
2) Provide your own base64 secret: pass --hmac-base64

Examples:
    uv run python scripts/setup_daily_webhook.py \
      --url https://backend-kalba.fly.dev/api/v1/video/webhooks/daily

    uv run python scripts/setup_daily_webhook.py \
      --url https://backend-kalba.fly.dev/api/v1/video/webhooks/daily \
      --hmac-base64 "<your-base64-secret>"
"""

from __future__ import annotations

import argparse
import base64
import binascii
import sys
from pathlib import Path

import httpx

# Ensure the app package is importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings

DAILY_API_BASE = "https://api.daily.co/v1"


def _is_valid_base64(value: str) -> bool:
    try:
        base64.b64decode(value, validate=True)
        return True
    except (ValueError, binascii.Error):
        return False


def _parse_events(events_arg: str) -> list[str]:
    events = [item.strip() for item in events_arg.split(",") if item.strip()]
    if not events:
        raise ValueError("At least one Daily event is required")
    return events


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a Daily.co webhook and print webhook secret details.",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Public endpoint that receives Daily webhooks, e.g. https://.../api/v1/video/webhooks/daily",
    )
    parser.add_argument(
        "--events",
        default="participant.joined,participant.left,meeting.ended",
        help="Comma-separated Daily webhook events.",
    )
    parser.add_argument(
        "--hmac-base64",
        default=None,
        help="Optional base64-encoded secret to set as webhook hmac.",
    )

    args = parser.parse_args()

    settings = get_settings()
    if not settings.daily_api_key:
        print("ERROR: DAILY_API_KEY is missing in environment.")
        return 1

    if args.hmac_base64 and not _is_valid_base64(args.hmac_base64):
        print("ERROR: --hmac-base64 must be valid base64.")
        return 1

    try:
        events = _parse_events(args.events)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    payload: dict[str, object] = {
        "url": args.url,
        "eventTypes": events,
    }
    if args.hmac_base64:
        payload["hmac"] = args.hmac_base64

    headers = {
        "Authorization": f"Bearer {settings.daily_api_key}",
        "Content-Type": "application/json",
    }

    print("Creating Daily webhook...")
    print(f"- URL: {args.url}")
    print(f"- Events: {', '.join(events)}")
    print(f"- Mode: {'custom hmac' if args.hmac_base64 else 'daily-generated hmac'}")

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(f"{DAILY_API_BASE}/webhooks", headers=headers, json=payload)

    if resp.status_code not in (200, 201):
        print(f"ERROR: Daily API returned {resp.status_code}")
        print(resp.text)
        return 1

    data = resp.json()
    webhook_id = data.get("id")
    webhook_url = data.get("url")
    webhook_hmac = data.get("hmac")

    print("\nWebhook created successfully:")
    print(f"- id: {webhook_id}")
    print(f"- url: {webhook_url}")

    if webhook_hmac:
        print("\nSet this environment variable:")
        print(f"DAILY_WEBHOOK_SECRET={webhook_hmac}")
    elif args.hmac_base64:
        print("\nDaily did not return hmac in response. Use the value you supplied:")
        print(f"DAILY_WEBHOOK_SECRET={args.hmac_base64}")
    else:
        print("\nWARNING: Daily response did not include 'hmac'.")
        print(
            "Check Daily dashboard/API response and set DAILY_WEBHOOK_SECRET manually."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
