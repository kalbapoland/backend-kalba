import logging

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

BREVO_API_BASE = "https://api.brevo.com/v3"


class EmailService:
    """Async wrapper around the Brevo transactional email API.

    Brevo's free tier supports single-sender verification, so the sender can be a
    plain address (e.g. a Gmail) verified by clicking a confirmation link — no
    domain ownership required.

    When no API key is configured the service degrades gracefully: instead of
    sending, it logs the message so that flows depending on email (e.g. password
    reset) still work end-to-end in local/dev environments.
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    @property
    def _enabled(self) -> bool:
        return bool(self._settings.brevo_api_key)

    async def send(self, *, to: str, subject: str, html: str) -> None:
        if not self._enabled:
            logger.warning(
                "Email sending disabled (no BREVO_API_KEY). Would send to %s "
                "with subject %r. Body: %s",
                to,
                subject,
                html,
            )
            return

        payload = {
            "sender": {
                "name": self._settings.email_from_name,
                "email": self._settings.email_from_address,
            },
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BREVO_API_BASE}/smtp/email",
                headers={
                    "api-key": self._settings.brevo_api_key,
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
                json=payload,
            )

        if resp.status_code >= 400:
            # Don't surface provider errors to the caller — password reset must
            # not leak whether an address exists, and a transient email failure
            # should not 500 the request.
            logger.error(
                "Brevo email to %s failed (%s): %s",
                to,
                resp.status_code,
                resp.text,
            )
            return

        logger.info("Email sent to %s (subject=%r)", to, subject)

    async def send_password_reset(self, *, to: str, reset_url: str) -> None:
        subject = "Reset your Kalba password"
        html = (
            "<div style=\"font-family: -apple-system, Segoe UI, Roboto, sans-serif; "
            "color: #1f2937; line-height: 1.6;\">"
            "<h2 style=\"font-weight: 600;\">Reset your password</h2>"
            "<p>We received a request to reset the password for your Kalba account. "
            "Tap the button below to choose a new password. This link expires in "
            f"{self._settings.password_reset_token_expire_minutes} minutes.</p>"
            f"<p><a href=\"{reset_url}\" style=\"display: inline-block; padding: 12px 20px; "
            "background: #0f766e; color: #ffffff; border-radius: 10px; text-decoration: none; "
            "font-weight: 600;\">Reset password</a></p>"
            "<p style=\"color: #6b7280; font-size: 13px;\">If you didn't request this, you "
            "can safely ignore this email — your password will stay the same.</p>"
            "<p style=\"color: #6b7280; font-size: 13px;\">Or paste this link into your browser:<br>"
            f"<span>{reset_url}</span></p>"
            "</div>"
        )
        await self.send(to=to, subject=subject, html=html)
