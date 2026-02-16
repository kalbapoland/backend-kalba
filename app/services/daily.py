import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

DAILY_API_BASE = "https://api.daily.co/v1"


class DailyServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class DailyService:
    """Async wrapper around the Daily.co REST API."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.daily_api_key}",
            "Content-Type": "application/json",
        }

    async def create_room(
        self,
        name: str,
        *,
        max_participants: int,
        start_time: datetime,
        duration_minutes: int,
    ) -> dict:
        """Create a Daily.co room. Returns the full room JSON."""
        # Room auto-expires 10 minutes after workshop ends,
        # but never in the past (for workshops already in progress)
        now_utc = datetime.now(UTC)
        exp = max(
            start_time.replace(tzinfo=UTC) + timedelta(minutes=duration_minutes + 10),
            now_utc + timedelta(minutes=10),
        )

        properties = {
            "max_participants": max_participants + 1,  # +1 for host
            "exp": int(exp.timestamp()),
            "enable_chat": True,
            "start_video_off": False,
            "start_audio_off": True,
            "enable_screenshare": False,
            "enable_recording": False,
            "enable_knocking": False,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{DAILY_API_BASE}/rooms",
                headers=self._headers,
                json={"name": name, "properties": properties},
            )

        if resp.status_code != 200:
            logger.error("Daily create_room failed: %s %s", resp.status_code, resp.text)
            raise DailyServiceError(resp.status_code, resp.text)

        return resp.json()

    async def send_app_message(
        self,
        room_name: str,
        data: dict,
        *,
        recipient: str = "*",
    ) -> None:
        """Send an app-message to participants in a Daily room."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{DAILY_API_BASE}/rooms/{room_name}/send-app-message",
                headers=self._headers,
                json={"data": data, "recipient": recipient},
            )

        if resp.status_code != 200:
            logger.error(
                "Daily send_app_message failed: %s %s",
                resp.status_code,
                resp.text,
            )
            raise DailyServiceError(resp.status_code, resp.text)

    async def delete_room(self, room_name: str) -> None:
        """Delete a Daily.co room."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{DAILY_API_BASE}/rooms/{room_name}",
                headers=self._headers,
            )
        if resp.status_code not in (200, 404):
            logger.error("Daily delete_room failed: %s %s", resp.status_code, resp.text)
            raise DailyServiceError(resp.status_code, resp.text)

    async def create_meeting_token(
        self,
        room_name: str,
        *,
        user_name: str,
        user_id: str,
        is_owner: bool = False,
        exp_minutes: int = 10,
        start_video_off: bool = False,
        start_audio_off: bool = True,
    ) -> str:
        """Generate a signed meeting token for a specific participant."""
        exp = datetime.now(UTC) + timedelta(minutes=exp_minutes)

        properties = {
            "room_name": room_name,
            "user_name": user_name,
            "user_id": user_id,
            "is_owner": is_owner,
            "exp": int(exp.timestamp()),
            "start_video_off": start_video_off,
            "start_audio_off": start_audio_off,
            "enable_screenshare": False,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{DAILY_API_BASE}/meeting-tokens",
                headers=self._headers,
                json={"properties": properties},
            )

        if resp.status_code != 200:
            logger.error(
                "Daily create_token failed: %s %s", resp.status_code, resp.text
            )
            raise DailyServiceError(resp.status_code, resp.text)

        return resp.json()["token"]

    @staticmethod
    def verify_webhook_signature(
        payload_body: bytes, signature: str, webhook_secret: str
    ) -> bool:
        """Verify that a webhook payload was signed by Daily.co."""
        expected = hmac.new(
            webhook_secret.encode(), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_daily_service() -> DailyService:
    """Factory / FastAPI dependency."""
    return DailyService()
