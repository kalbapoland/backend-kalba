"""Test script to verify Daily.co integration works end-to-end.

Run from backend-kalba/:
    uv run python scripts/test_daily.py
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure the app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services.daily import DailyService, DailyServiceError


async def main() -> None:
    settings = get_settings()
    daily = DailyService(settings)

    print("=== Daily.co Integration Test ===\n")
    print(f"Domain: {settings.daily_domain}")
    print(f"API key: {settings.daily_api_key[:8]}...{settings.daily_api_key[-4:]}\n")

    room_name = "kalba-test-integration"

    # 1. Create a room
    print("1. Creating test room...")
    try:
        room = await daily.create_room(
            name=room_name,
            max_participants=5,
            start_time=datetime.now(UTC),
            duration_minutes=30,
        )
        print(f"   Room created: {room['url']}")
        print(f"   Room name:    {room['name']}")
        print(f"   Room ID:      {room['id']}")
    except DailyServiceError as e:
        print(f"   FAILED: {e.status_code} - {e.detail}")
        return

    # 2. Generate a host token
    print("\n2. Generating host meeting token...")
    try:
        host_token = await daily.create_meeting_token(
            room_name=room_name,
            user_name="Test Trainer",
            user_id="trainer-001",
            is_owner=True,
            exp_minutes=30,
        )
        print(f"   Host token: {host_token[:40]}...")
    except DailyServiceError as e:
        print(f"   FAILED: {e.status_code} - {e.detail}")

    # 3. Generate a participant token
    print("\n3. Generating participant meeting token...")
    try:
        participant_token = await daily.create_meeting_token(
            room_name=room_name,
            user_name="Test Student",
            user_id="student-001",
            is_owner=False,
            exp_minutes=30,
            start_audio_off=True,
            start_video_off=False,
        )
        print(f"   Participant token: {participant_token[:40]}...")
    except DailyServiceError as e:
        print(f"   FAILED: {e.status_code} - {e.detail}")

    # 4. Print join URLs for manual testing
    room_url = f"https://{settings.daily_domain}/{room_name}"
    print("\n4. Join URLs for manual testing:")
    print(f"   Room URL:  {room_url}")
    print(f"   Host URL:  {room_url}?t={host_token}")
    print(f"   Guest URL: {room_url}?t={participant_token}")
    print("\n   Open these URLs in a browser to test video calls!")

    # 5. Clean up
    print("\n5. Cleaning up test room...")
    try:
        await daily.delete_room(room_name)
        print("   Room deleted.")
    except DailyServiceError as e:
        print(f"   FAILED to delete: {e.status_code} - {e.detail}")

    print("\n=== All tests passed! ===")


if __name__ == "__main__":
    asyncio.run(main())
