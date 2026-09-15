import json
import logging
from collections.abc import Mapping

from constance import config
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

logger = logging.getLogger("emails")

BACKEND_CLASSES = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "locmem": "django.core.mail.backends.locmem.EmailBackend",
    "postmark": "services.email_backends.PostmarkEmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
}


def _get_backend_options(backend_name):
    raw_options = config.EMAIL_BACKEND_OPTIONS
    try:
        all_options = (
            json.loads(raw_options) if isinstance(raw_options, str) else raw_options
        )
    except json.JSONDecodeError as error:
        raise ImproperlyConfigured(
            "EMAIL_BACKEND_OPTIONS must be valid JSON."
        ) from error

    if not isinstance(all_options, Mapping):
        raise ImproperlyConfigured(
            "EMAIL_BACKEND_OPTIONS must be a JSON object keyed by backend name."
        )

    backend_options = all_options.get(backend_name, {})
    if not isinstance(backend_options, Mapping):
        raise ImproperlyConfigured(
            f"EMAIL_BACKEND_OPTIONS.{backend_name} must be a JSON object."
        )

    return dict(backend_options)


def _get_email_connection():
    if not config.EMAIL_ENABLED or config.EMAIL_BACKEND == "disabled":
        return None

    backend_name = str(config.EMAIL_BACKEND).strip().lower()
    backend_class = BACKEND_CLASSES.get(backend_name)
    if backend_class is None:
        supported_backends = ", ".join(sorted(BACKEND_CLASSES))
        raise ImproperlyConfigured(
            f"Unsupported EMAIL_BACKEND '{backend_name}'. "
            f"Supported values: {supported_backends}, disabled."
        )

    backend_options = _get_backend_options(backend_name)
    if backend_name == "smtp" and not backend_options.get("host"):
        raise ImproperlyConfigured(
            "SMTP email backend requires EMAIL_BACKEND_OPTIONS.smtp.host."
        )

    return get_connection(
        backend=backend_class,
        fail_silently=False,
        **backend_options,
    )


def _template_context(template_vars):
    if not isinstance(template_vars, Mapping):
        raise TypeError("template_vars must be a mapping.")

    email_vars = dict(template_vars)
    if email_vars.get("message"):
        message = escape(str(email_vars["message"]))
        email_vars["message"] = mark_safe(message.replace("~br~", "<br>"))
    if email_vars.get("title"):
        email_vars["title"] = escape(str(email_vars["title"]))

    return email_vars


def _log_email_event(user, event, template_name):
    if user:
        user.log_event(event, "email", f"Email template: {template_name}")


def send_single_email(
    to_email: str,
    subject: str,
    template_vars: Mapping,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> bool:
    # TODO: move to celery
    template_to_use = template_name or "email_without_button.html"
    logger.debug("Using email template: %s", template_to_use)

    connection = _get_email_connection()
    if connection is None:
        logger.warning("Email delivery is disabled by configuration.")
        _log_email_event(
            user,
            f"Email not sent due to configuration issue: {subject}",
            template_to_use,
        )
        return False

    email_string = render_to_string(
        template_to_use,
        {"email": _template_context(template_vars), "config": config},
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(email_string),
        from_email=config.EMAIL_DEFAULT_FROM,
        to=[to_email],
        reply_to=[reply_to or config.EMAIL_DEFAULT_FROM],
        connection=connection,
    )
    message.attach_alternative(email_string, "text/html")

    sent = message.send() == 1
    if sent:
        logger.info("Email sent to %s with subject: %s", to_email, subject)
        _log_email_event(user, f"Sent email with subject: {subject}", template_to_use)
    else:
        logger.warning("Email was not accepted for delivery to %s.", to_email)
        _log_email_event(
            user,
            f"Email not sent by configured backend: {subject}",
            template_to_use,
        )
    return sent


def send_email_to_admin(
    subject: str,
    template_vars: Mapping,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> bool:
    return send_single_email(
        config.EMAIL_ADMIN,
        subject,
        template_vars,
        template_name=template_name,
        reply_to=reply_to,
        user=user,
    )
