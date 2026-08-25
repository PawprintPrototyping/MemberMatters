import os
from django.conf.urls import url
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "membermatters.settings")
django_asgi_app = get_asgi_application()

# Sentry init happens here (main thread, pre-event-loop) rather than in
# urls.py, which is loaded lazily on the first request from inside the
# ASGI event loop and can't safely touch the ORM.
from membermatters.sentry_init import init_sentry_from_constance

init_sentry_from_constance()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from membermatters.websocket_urls import urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(urlpatterns)),
    }
)
