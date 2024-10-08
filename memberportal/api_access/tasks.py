from membermatters.celeryapp import app
import os
import logging

logger = logging.getLogger("api_access:tasks")


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        3600 if os.environ.get("MM_ENV") == "Production" else 30,
        heartbeat_logger.s(),
        expires=10,
        name="celery_heartbeat_logger",
    )


@app.task
def heartbeat_logger():
    logger.debug("Celery is alive!")
