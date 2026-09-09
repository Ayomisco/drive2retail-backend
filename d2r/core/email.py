"""Resend email backend.

Wraps Resend in Django's mail interface so `send_mail`, password reset and the
notification layer all work unchanged, and tests can swap in locmem.
"""

from __future__ import annotations

import logging

import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently: bool = False, **kwargs) -> None:
        super().__init__(fail_silently=fail_silently, **kwargs)
        resend.api_key = settings.RESEND_API_KEY

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            try:
                payload = {
                    "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
                    "to": list(message.to),
                    "subject": message.subject,
                    "text": message.body,
                }
                if message.cc:
                    payload["cc"] = list(message.cc)
                if message.bcc:
                    payload["bcc"] = list(message.bcc)
                if message.reply_to:
                    payload["reply_to"] = list(message.reply_to)

                # HTML alternative, when the caller attached one
                for content, mimetype in getattr(message, "alternatives", []):
                    if mimetype == "text/html":
                        payload["html"] = content

                resend.Emails.send(payload)
                sent += 1
            except Exception:
                logger.exception("resend.send_failed", extra={"subject": message.subject})
                if not self.fail_silently:
                    raise
        return sent
