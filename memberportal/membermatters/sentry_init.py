"""Sentry backend initialiser, shared by every process entrypoint.

Historically Sentry was initialised at module load of ``urls.py``. That
runs lazily on the first HTTP request, which under daphne/ASGI is
already inside the event loop - Django then refuses the constance ORM
lookup with ``SynchronousOnlyOperation``.

Calling ``init_sentry_from_constance()`` from ``asgi.py``, ``wsgi.py``
and ``celeryapp.py`` moves the same work to process startup on the main
thread, before any request-handling loop runs. ``urls.py`` is only
loaded by the web entrypoints, so initialising there meant celery
workers and beat never reported anything at all.
"""

import json
import logging
import os

import django.db.utils
import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration

logger = logging.getLogger("membermatters.sentry_init")

# PID of the process that last completed initialisation. Keyed on the PID
# rather than a plain bool because celery's prefork pool forks children
# that inherit this module's state but *not* the parent's sentry
# transport thread - they need to re-init rather than no-op.
_initialised_pid = None


def _read_release_from_package_json():
    """Return the version from the repo-root package.json, or None.

    Resolved from ``settings.BASE_DIR`` rather than the CWD: this module
    is imported from wsgi.py, which `runserver` and any external WSGI
    server load with an arbitrary working directory.
    """
    from django.conf import settings

    path = os.path.join(os.path.dirname(settings.BASE_DIR), "package.json")
    try:
        with open(path) as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        logger.warning("Could not read release version from %s", path)
        return None


def init_sentry_from_constance():
    """Initialise Sentry using a DSN stored in constance.

    Idempotent per process. No-ops when:
      * no DSN is configured (default),
      * MM_ENV is a development environment (settings.IS_PRODUCTION is False),
      * the constance_config table isn't available yet (fresh DB before
        migrations run) - in that case a later call can still succeed.
    """
    global _initialised_pid

    if _initialised_pid == os.getpid():
        return

    try:
        from constance import config  # imported lazily so Django is set up first

        dsn = getattr(config, "SENTRY_DSN_BACKEND", "")
        if not dsn or not settings.IS_PRODUCTION:
            _initialised_pid = os.getpid()
            return

        sentry_sdk.init(
            release=os.environ.get("SENTRY_RELEASE", _read_release_from_package_json()),
            environment=os.environ.get("SENTRY_ENVIRONMENT", settings.ENVIRONMENT),
            dsn=dsn,
            integrations=[DjangoIntegration()],
        )
        _initialised_pid = os.getpid()

    # On first boot the constance_config table doesn't exist until
    # migrations run. Postgres raises ProgrammingError, SQLite raises
    # OperationalError - both inherit from DatabaseError. Deliberately
    # leaves _initialised_pid unset so a later call retries once the
    # migrations have been applied.
    except django.db.utils.DatabaseError:
        logger.warning(
            "Skipping Sentry init: constance config unavailable "
            "(database not migrated or unreachable)."
        )
