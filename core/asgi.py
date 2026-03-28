"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application
from deploy_bootstrap import configure_django_entrypoint_defaults
from .settings_bootstrap import configure_settings

configure_django_entrypoint_defaults()
configure_settings('core.settings_production')

django_asgi_app = get_asgi_application()

from sales.realtime import EnforceSecureWebSocketMiddleware, TenantJWTAuthMiddleware
from sales.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
	'http': django_asgi_app,
	'websocket': OriginValidator(
		EnforceSecureWebSocketMiddleware(
			TenantJWTAuthMiddleware(
				URLRouter(websocket_urlpatterns)
			)
		),
		getattr(settings, 'WEBSOCKET_ALLOWED_ORIGINS', []),
	),
})
