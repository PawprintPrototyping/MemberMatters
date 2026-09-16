import logging

from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend
from postmarker.core import ClientError, PostmarkClient

logger = logging.getLogger("emails")


class PostmarkEmailBackend(BaseEmailBackend):
    """Send Django email messages through Postmark's existing client."""

    def __init__(self, server_token=None, **kwargs):
        super().__init__(**kwargs)
        self.server_token = server_token

    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        if not self.server_token:
            raise ImproperlyConfigured(
                "Postmark email backend requires a server_token option."
            )

        client = PostmarkClient(server_token=self.server_token)
        sent_count = 0

        for message in email_messages:
            try:
                self._send_message(client, message)
            except ClientError as error:
                if error.error_code == 406:
                    logger.warning(
                        "Email not sent because the Postmark recipient is inactive."
                    )
                    continue
                if self.fail_silently:
                    logger.exception("Postmark rejected an email message.")
                    continue
                raise
            except Exception:
                if self.fail_silently:
                    logger.exception("Postmark failed to send an email message.")
                    continue
                raise
            sent_count += 1

        return sent_count

    @staticmethod
    def _send_message(client, message):
        payload = {
            "From": message.from_email,
            "To": ", ".join(message.to),
            "Subject": message.subject,
            "TextBody": message.body,
        }
        if message.cc:
            payload["Cc"] = ", ".join(message.cc)
        if message.bcc:
            payload["Bcc"] = ", ".join(message.bcc)
        html_body = next(
            (
                content
                for content, mimetype in getattr(message, "alternatives", [])
                if mimetype == "text/html"
            ),
            None,
        )
        if html_body is not None:
            payload["HtmlBody"] = html_body
        if message.reply_to:
            payload["ReplyTo"] = message.reply_to[0]

        client.emails.send(**payload)
