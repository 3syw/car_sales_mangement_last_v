from urllib.parse import parse_qs

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings

from .tenant_database import ensure_tenant_connection, normalize_tenant_id


def tenant_group_name(tenant_id):
    return f"tenant-events-{normalize_tenant_id(tenant_id)}"


def publish_tenant_event(*, tenant_id, topic, event, payload):
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    if not normalized_tenant_id:
        return

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        tenant_group_name(normalized_tenant_id),
        {
            'type': 'tenant.event',
            'event': event,
            'topic': topic,
            'tenant_id': normalized_tenant_id,
            'payload': payload,
            'timestamp': timezone.now().isoformat(),
        },
    )


@database_sync_to_async
def _resolve_user_from_token(token_value):
    authenticator = JWTAuthentication()
    validated_token = authenticator.get_validated_token(token_value)
    tenant_id = normalize_tenant_id(validated_token.get('tenant_id'))
    if not tenant_id:
        raise InvalidToken('Missing tenant claim')

    tenant_alias = ensure_tenant_connection(tenant_id)
    if not tenant_alias:
        raise InvalidToken('Missing tenant database')

    user_model = get_user_model()
    user_id = validated_token.get(api_settings.USER_ID_CLAIM)
    user = user_model.objects.using(tenant_alias).get(pk=user_id)
    return user, tenant_id, tenant_alias


class TenantJWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope['user'] = AnonymousUser()
        scope['tenant_id'] = ''
        scope['tenant_db_alias'] = ''

        token_value = ''
        for header_name, header_value in scope.get('headers', []):
            if header_name == b'authorization':
                raw_header = header_value.decode('utf-8')
                if raw_header.lower().startswith('bearer '):
                    token_value = raw_header.split(' ', 1)[1].strip()
                    break

        if not token_value:
            query_params = parse_qs((scope.get('query_string') or b'').decode('utf-8'))
            token_value = (query_params.get('token') or [''])[0].strip()

        if token_value:
            try:
                user, tenant_id, tenant_alias = await _resolve_user_from_token(token_value)
                scope['user'] = user
                scope['tenant_id'] = tenant_id
                scope['tenant_db_alias'] = tenant_alias
            except Exception:
                pass

        return await super().__call__(scope, receive, send)


class EnforceSecureWebSocketMiddleware(BaseMiddleware):
    """Block non-secure websocket handshakes in production deployments."""

    async def __call__(self, scope, receive, send):
        if getattr(settings, 'DEBUG', False):
            return await super().__call__(scope, receive, send)

        headers = {
            key.decode('utf-8').lower(): value.decode('utf-8')
            for key, value in scope.get('headers', [])
        }
        forwarded_proto = headers.get('x-forwarded-proto', '')
        scope_scheme = (scope.get('scheme') or '').lower()
        is_secure = scope_scheme in {'wss', 'https'} or 'https' in forwarded_proto.lower()

        if not is_secure:
            await send({'type': 'websocket.close', 'code': 4400})
            return

        return await super().__call__(scope, receive, send)