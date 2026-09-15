from unittest.mock import Mock, patch

from constance.test.unittest import override_config
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase
from postmarker.core import ClientError

from services import email_backends, emails


class EmailServiceTests(TestCase):
    email_config = {
        "EMAIL_ENABLED": True,
        "EMAIL_BACKEND": "locmem",
        "EMAIL_BACKEND_OPTIONS": "{}",
        "EMAIL_DEFAULT_FROM": "MemberMatters <noreply@example.test>",
        "EMAIL_ADMIN": "admin@example.test",
    }

    def test_template_context_escapes_content_without_mutating_input(self):
        template_vars = {
            "title": "<Title>",
            "message": "<Message>~br~Next line",
        }

        context = emails._template_context(template_vars)

        self.assertEqual(template_vars["title"], "<Title>")
        self.assertEqual(template_vars["message"], "<Message>~br~Next line")
        self.assertEqual(str(context["title"]), "&lt;Title&gt;")
        self.assertEqual(str(context["message"]), "&lt;Message&gt;<br>Next line")

    def test_backend_options_reject_invalid_json_and_non_object_profiles(self):
        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="locmem",
            EMAIL_BACKEND_OPTIONS="not-json",
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "EMAIL_BACKEND_OPTIONS must be valid JSON.",
            ):
                emails._get_backend_options("locmem")

        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="locmem",
            EMAIL_BACKEND_OPTIONS="[]",
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "EMAIL_BACKEND_OPTIONS must be a JSON object keyed by backend name.",
            ):
                emails._get_backend_options("locmem")

        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="locmem",
            EMAIL_BACKEND_OPTIONS='{"locmem": []}',
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "EMAIL_BACKEND_OPTIONS.locmem must be a JSON object.",
            ):
                emails._get_backend_options("locmem")

    def test_connection_rejects_unknown_backend(self):
        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="unknown",
            EMAIL_BACKEND_OPTIONS="{}",
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "Unsupported EMAIL_BACKEND 'unknown'.",
            ):
                emails._get_email_connection()

    def test_connection_uses_allowlisted_smtp_backend_and_options(self):
        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="SMTP",
            EMAIL_BACKEND_OPTIONS='{"smtp": {"host": "smtp.example.test"}}',
        ):
            with patch("services.emails.get_connection") as get_connection:
                emails._get_email_connection()

        get_connection.assert_called_once_with(
            backend="django.core.mail.backends.smtp.EmailBackend",
            fail_silently=False,
            host="smtp.example.test",
        )

    def test_connection_rejects_missing_smtp_host(self):
        with override_config(
            EMAIL_ENABLED=True,
            EMAIL_BACKEND="smtp",
            EMAIL_BACKEND_OPTIONS="{}",
        ):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "SMTP email backend requires EMAIL_BACKEND_OPTIONS.smtp.host.",
            ):
                emails._get_email_connection()

    def test_disabled_email_does_not_render_or_send(self):
        user = Mock()
        with override_config(
            EMAIL_ENABLED=False,
            EMAIL_BACKEND="locmem",
            EMAIL_BACKEND_OPTIONS="{}",
        ):
            with patch("services.emails.render_to_string") as render_to_string:
                sent = emails.send_single_email(
                    "member@example.test",
                    "Subject",
                    {"title": "Title", "message": "Message"},
                    user=user,
                )

        self.assertFalse(sent)
        render_to_string.assert_not_called()
        user.log_event.assert_called_once_with(
            "Email not sent due to configuration issue: Subject",
            "email",
            "Email template: email_without_button.html",
        )

    def test_send_single_email_sends_text_and_html_alternatives(self):
        user = Mock()
        with override_config(**self.email_config):
            with patch(
                "services.emails.render_to_string",
                return_value="<h1>Title</h1><p>Message</p>",
            ) as render_to_string:
                sent = emails.send_single_email(
                    "member@example.test",
                    "Subject",
                    {"title": "Title", "message": "Message"},
                    reply_to="reply@example.test",
                    user=user,
                )

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, self.email_config["EMAIL_DEFAULT_FROM"])
        self.assertEqual(message.to, ["member@example.test"])
        self.assertEqual(message.reply_to, ["reply@example.test"])
        self.assertEqual(message.body, "TitleMessage")
        self.assertEqual(
            message.alternatives,
            [("<h1>Title</h1><p>Message</p>", "text/html")],
        )
        self.assertEqual(
            render_to_string.call_args.args[1]["email"],
            {"title": "Title", "message": "Message"},
        )
        user.log_event.assert_called_once_with(
            "Sent email with subject: Subject",
            "email",
            "Email template: email_without_button.html",
        )

    def test_send_single_email_records_backend_rejection(self):
        user = Mock()
        message = Mock()
        message.send.return_value = 0

        with override_config(**self.email_config):
            with patch(
                "services.emails.render_to_string",
                return_value="<p>Message</p>",
            ):
                with patch(
                    "services.emails.EmailMultiAlternatives",
                    return_value=message,
                ):
                    sent = emails.send_single_email(
                        "member@example.test",
                        "Subject",
                        {"title": "Title", "message": "Message"},
                        user=user,
                    )

        self.assertFalse(sent)
        user.log_event.assert_called_once_with(
            "Email not sent by configured backend: Subject",
            "email",
            "Email template: email_without_button.html",
        )

    def test_send_email_to_admin_forwards_to_configured_recipient(self):
        with override_config(EMAIL_ADMIN="admin@example.test"):
            with patch("services.emails.send_single_email", return_value=True) as send:
                result = emails.send_email_to_admin(
                    "Subject",
                    {"title": "Title", "message": "Message"},
                )

        self.assertTrue(result)
        send.assert_called_once_with(
            "admin@example.test",
            "Subject",
            {"title": "Title", "message": "Message"},
            template_name=None,
            reply_to=None,
            user=None,
        )


class PostmarkEmailBackendTests(TestCase):
    def test_send_messages_maps_django_recipient_categories_and_content(self):
        message = EmailMultiAlternatives(
            subject="Subject",
            body="Plain text",
            from_email="from@example.test",
            to=["to@example.test"],
            cc=["cc@example.test"],
            bcc=["bcc@example.test"],
            reply_to=["reply@example.test"],
        )
        message.attach_alternative("<p>HTML</p>", "text/html")
        client = Mock()

        with patch("services.email_backends.PostmarkClient", return_value=client):
            sent = email_backends.PostmarkEmailBackend(
                server_token="token"
            ).send_messages([message])

        self.assertEqual(sent, 1)
        client.emails.send.assert_called_once_with(
            From="from@example.test",
            To="to@example.test",
            Cc="cc@example.test",
            Bcc="bcc@example.test",
            Subject="Subject",
            TextBody="Plain text",
            HtmlBody="<p>HTML</p>",
            ReplyTo="reply@example.test",
        )

    def test_send_messages_requires_postmark_token_for_nonempty_messages(self):
        message = EmailMultiAlternatives(
            subject="Subject",
            body="Body",
            from_email="from@example.test",
            to=["to@example.test"],
        )

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Postmark email backend requires a server_token option.",
        ):
            email_backends.PostmarkEmailBackend().send_messages([message])

    def test_empty_message_collection_does_not_require_postmark_token(self):
        self.assertEqual(email_backends.PostmarkEmailBackend().send_messages([]), 0)

    def test_postmark_client_error_is_ignored_when_fail_silently(self):
        message = EmailMultiAlternatives(
            subject="Subject",
            body="Body",
            from_email="from@example.test",
            to=["to@example.test"],
        )
        client = Mock()
        client.emails.send.side_effect = ClientError("rejected", error_code=500)

        with self.assertLogs("emails", level="ERROR"):
            with patch("services.email_backends.PostmarkClient", return_value=client):
                sent = email_backends.PostmarkEmailBackend(
                    server_token="token",
                    fail_silently=True,
                ).send_messages([message])

        self.assertEqual(sent, 0)
        client.emails.send.assert_called_once()

    def test_inactive_postmark_recipient_is_not_counted_as_sent(self):
        message = EmailMultiAlternatives(
            subject="Subject",
            body="Body",
            from_email="from@example.test",
            to=["to@example.test"],
        )
        client = Mock()
        client.emails.send.side_effect = ClientError("inactive", error_code=406)

        with patch("services.email_backends.PostmarkClient", return_value=client):
            sent = email_backends.PostmarkEmailBackend(
                server_token="token"
            ).send_messages([message])

        self.assertEqual(sent, 0)
        client.emails.send.assert_called_once()
