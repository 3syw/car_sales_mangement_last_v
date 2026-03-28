from django.urls import re_path

from .consumers import TenantEventsConsumer


websocket_urlpatterns = [
    re_path(r'^ws/tenants/(?P<tenant_id>[a-z0-9_-]+)/events/$', TenantEventsConsumer.as_asgi()),
]