import os
from celery import Celery
from celery.signals import beat_init, worker_process_init
import logging

logger = logging.getLogger("celery:celeryapp")

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")

app = Celery("membermatters")


# Celery loads neither wsgi.py nor asgi.py, so without this tasks would run
# with Sentry uninitialised. Deferred to signals because init queries constance
# via the ORM, which isn't ready at module import; worker_process_init also
# re-inits per prefork child, which doesn't inherit sentry's transport thread.
@worker_process_init.connect
@beat_init.connect
def _init_sentry(**_kwargs):
    from membermatters.sentry_init import init_sentry_from_constance

    init_sentry_from_constance()


# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    logger.debug(f"Request: {self.request!r}")
