from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import permissions, serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .tenant_context import set_current_tenant
from .tenant_database import ensure_tenant_connection, normalize_tenant_id
from .tenant_registry import get_cached_tenant_metadata, is_valid_tenant_access_key
from .models import AuditLog
from .realtime import publish_tenant_event


def _resolve_client_ip(request):
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        return xff.split(',')[0].strip()
    return (request.META.get('REMOTE_ADDR') or '').strip()


def _classify_device(user_agent):
    ua = (user_agent or '').lower()
    for keyword in ['iphone', 'android', 'mobile', 'ipad']:
        if keyword in ua:
            return 'mobile'
    return 'desktop' if ua else ''


def _classify_browser(user_agent):
    ua = (user_agent or '').lower()
    if 'edg/' in ua:
        return 'Edge'
    if 'chrome/' in ua and 'edg/' not in ua:
        return 'Chrome'
    if 'firefox/' in ua:
        return 'Firefox'
    if 'safari/' in ua and 'chrome/' not in ua:
        return 'Safari'
    return ''


def _write_geo_change_alert(request, *, tenant_alias, tenant_id, user):
    if request is None or user is None:
        return

    current_geo = (
        request.META.get('HTTP_CF_IPCOUNTRY')
        or request.META.get('HTTP_X_APPENGINE_COUNTRY')
        or ''
    ).strip().upper()
    if not current_geo:
        return

    cache_key = f"sec:last-login-geo:{tenant_id}:{user.username.lower()}"
    previous_geo = (cache.get(cache_key) or '').strip().upper()
    cache.set(cache_key, current_geo, timeout=60 * 60 * 24 * 60)

    if not previous_geo or previous_geo == current_geo:
        return

    user_agent = request.META.get('HTTP_USER_AGENT') or ''
    ip_address = _resolve_client_ip(request)
    alert_payload = {
        'alert_type': 'geo_login_anomaly',
        'username': user.username,
        'tenant_id': tenant_id,
        'previous_country': previous_geo,
        'current_country': current_geo,
        'ip_address': ip_address,
    }

    AuditLog.objects.using(tenant_alias).create(
        user=user,
        tenant_id=tenant_id,
        action='security_alert',
        target_model='AuthLogin',
        target_pk=str(user.pk),
        before_data={'country': previous_geo},
        after_data={'country': current_geo},
        ip_address=ip_address,
        device_type=_classify_device(user_agent),
        browser=_classify_browser(user_agent),
        geo_location=current_geo,
        request_path=request.path,
    )

    publish_tenant_event(
        tenant_id=tenant_id,
        topic='security',
        event='security.alert',
        payload=alert_payload,
    )


class TenantTokenObtainPairSerializer(TokenObtainPairSerializer):
    tenant_id = serializers.CharField(write_only=True)
    tenant_key = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        tenant_id = normalize_tenant_id(self.initial_data.get('tenant_id'))
        tenant_key = (self.initial_data.get('tenant_key') or '').strip()
        username = (attrs.get('username') or self.initial_data.get('username') or '').strip()
        password = attrs.get('password')

        if not tenant_id or not tenant_key or not username or not password:
            raise AuthenticationFailed('يجب إدخال معرف المعرض ومفتاحه وبيانات المستخدم.')

        tenant_metadata = get_cached_tenant_metadata(tenant_id)
        if tenant_metadata is None or not tenant_metadata.get('is_active') or tenant_metadata.get('is_deleted'):
            raise AuthenticationFailed('بيئة المعرض غير صالحة أو غير نشطة.')

        if not is_valid_tenant_access_key(tenant_metadata, tenant_key):
            raise AuthenticationFailed('مفتاح الوصول للمعرض غير صحيح.')

        tenant_alias = ensure_tenant_connection(tenant_id)
        if not tenant_alias:
            raise AuthenticationFailed('تعذر تهيئة اتصال قاعدة بيانات المعرض.')

        user_model = get_user_model()
        try:
            user = user_model.objects.using(tenant_alias).get(username=username)
        except user_model.DoesNotExist as exc:
            raise AuthenticationFailed('بيانات تسجيل الدخول غير صحيحة.') from exc

        if not user.check_password(password) or not user.is_active:
            raise AuthenticationFailed('بيانات تسجيل الدخول غير صحيحة.')

        refresh = super().get_token(user)
        refresh['tenant_id'] = tenant_id
        refresh['tenant_alias'] = tenant_alias
        refresh['username'] = user.username
        set_current_tenant(tenant_id, tenant_alias)
        _write_geo_change_alert(self.context.get('request'), tenant_alias=tenant_alias, tenant_id=tenant_id, user=user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'tenant_id': tenant_id,
            'tenant_alias': tenant_alias,
            'username': user.username,
            'is_superuser': user.is_superuser,
        }


class TenantTokenObtainPairView(TokenObtainPairView):
    serializer_class = TenantTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class TenantTokenRefreshView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]


class CurrentUserAPIView(APIView):
    def get(self, request):
        return Response({
            'id': request.user.pk,
            'username': request.user.username,
            'is_superuser': request.user.is_superuser,
            'tenant_id': getattr(request, 'tenant_id', ''),
            'tenant_alias': getattr(request, 'tenant_db_alias', ''),
        })