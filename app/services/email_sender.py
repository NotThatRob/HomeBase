from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.config import Settings

RESEND_EMAILS_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class EmailSendResult:
    status: str
    detail: str
    provider_id: str | None = None

    @property
    def sent(self) -> bool:
        return self.status == "sent"


def send_email(
    message: EmailMessage,
    settings: Settings,
    *,
    dry_run: bool = False,
    opener=urllib.request.urlopen,
) -> EmailSendResult:
    if dry_run:
        return EmailSendResult("dry_run", f"Would send email to {message.to}")
    if not settings.email_enabled:
        return EmailSendResult("skipped", "Email delivery is disabled")
    if not settings.resend_api_key:
        return EmailSendResult("skipped", "RESEND_API_KEY is not configured")

    payload = {
        "from": settings.email_from,
        "to": [message.to],
        "subject": message.subject,
        "html": message.html,
        "text": message.text,
    }
    request = urllib.request.Request(
        RESEND_EMAILS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with opener(request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return EmailSendResult("failed", f"Resend HTTP {exc.code}")
    except OSError as exc:
        return EmailSendResult("failed", str(exc))

    return EmailSendResult("sent", "Email sent", provider_id=body.get("id"))
