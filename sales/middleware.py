from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils.translation import get_language
from .models import AuditLog, InterfaceAccess, OperationLog
from .translation_catalog import UI_TRANSLATIONS
from .audit import set_request_audit_context, clear_request_audit_context
from .realtime import publish_tenant_event
from .tenant_context import clear_current_tenant, set_current_tenant, get_current_tenant_db_alias
from .tenant_database import ensure_tenant_connection, normalize_tenant_id
from .tenant_registry import get_cached_tenant_metadata


class TenantMiddleware:
    EXCLUDED_PATH_PREFIXES = ('/static/', '/media/', '/admin/jsi18n/')
    TENANT_DB_ALIAS_SESSION_KEY = 'tenant_db_alias'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_current_tenant()

        path = request.path or ''
        if path.startswith(self.EXCLUDED_PATH_PREFIXES):
            return self.get_response(request)

        tenant_id = normalize_tenant_id(request.session.get('tenant_id'))
        tenant_alias = (request.session.get(self.TENANT_DB_ALIAS_SESSION_KEY) or '').strip()
        if path.startswith('/api/'):
            header_tenant_id = normalize_tenant_id(request.META.get('HTTP_X_TENANT_ID'))
            if tenant_id and header_tenant_id and header_tenant_id != tenant_id:
                raise PermissionDenied('لا يمكن تبديل بيئة المعرض عبر الترويسة داخل جلسة نشطة.')

        if tenant_id:
            tenant_metadata = get_cached_tenant_metadata(tenant_id)
            if tenant_metadata and tenant_metadata.get('is_active'):
                alias = ensure_tenant_connection(tenant_id)
                if alias:
                    set_current_tenant(tenant_id, alias)
                    if tenant_alias != alias:
                        request.session[self.TENANT_DB_ALIAS_SESSION_KEY] = alias
        elif tenant_alias.startswith('tenant_'):
            fallback_tenant_id = normalize_tenant_id(tenant_alias[len('tenant_'):])
            if fallback_tenant_id:
                alias = ensure_tenant_connection(fallback_tenant_id)
                if alias:
                    set_current_tenant(fallback_tenant_id, alias)
                    request.session['tenant_id'] = fallback_tenant_id

        response = self.get_response(request)

        add_post_render_callback = getattr(response, 'add_post_render_callback', None)
        if callable(add_post_render_callback) and not getattr(response, 'is_rendered', True):
            def _clear_tenant_after_render(rendered_response):
                clear_current_tenant()
                return rendered_response

            response.add_post_render_callback(_clear_tenant_after_render)
            return response

        clear_current_tenant()
        return response


class InterfaceAccessMiddleware:
    PATH_TO_PERMISSION = {
        '/dashboard/': 'can_access_dashboard',
        '/cars/': 'can_access_cars',
        '/reports/': 'can_access_reports',
        '/debts/': 'can_access_debts',
        '/timeline/': 'can_access_timeline',
        '/admin/auth/user/list/': 'can_access_system_users',
        '/admin/sales/car/available/': 'can_access_cars',
        '/admin/sales/car/sold/': 'can_access_cars',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if request.session.get('platform_owner_authenticated'):
            return self.get_response(request)

        if user is None or not user.is_authenticated or user.is_superuser:
            return self.get_response(request)

        tenant_alias = (get_current_tenant_db_alias() or '').strip()
        if not tenant_alias.startswith('tenant_'):
            return self.get_response(request)

        path = request.path or ''
        permission_field = self._resolve_permission_field(path)
        if permission_field:
            access, _ = InterfaceAccess.objects.using(tenant_alias).get_or_create(user=user)
            if not getattr(access, permission_field, True):
                raise PermissionDenied('ليس لديك صلاحية للوصول إلى هذه الواجهة.')

        return self.get_response(request)

    def _resolve_permission_field(self, path):
        for prefix, permission_field in self.PATH_TO_PERMISSION.items():
            if path.startswith(prefix):
                return permission_field
        return None


class OperationLogMiddleware:
    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return (request.META.get('REMOTE_ADDR') or '').strip()

    @staticmethod
    def _classify_device(user_agent):
        ua = (user_agent or '').lower()
        if not ua:
            return ''
        mobile_keywords = ['iphone', 'android', 'mobile', 'ipad']
        for keyword in mobile_keywords:
            if keyword in ua:
                return 'mobile'
        return 'desktop'

    @staticmethod
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

    @staticmethod
    def _resolve_geo_hint(request):
        for key in ['HTTP_CF_IPCOUNTRY', 'HTTP_X_APPENGINE_COUNTRY']:
            value = (request.META.get(key) or '').strip()
            if value:
                return value
        return ''

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _is_export_request(request, response):
        path = (request.path or '').lower()
        content_disposition = ''
        if hasattr(response, 'get'):
            content_disposition = (response.get('Content-Disposition') or '').lower()
        elif hasattr(response, 'headers'):
            content_disposition = (response.headers.get('Content-Disposition') or '').lower()

        is_export_path = '/export/' in path or path.endswith('/export')
        is_attachment = 'attachment' in content_disposition
        return is_export_path or is_attachment

    @staticmethod
    def _resolve_request_tenant(request):
        alias = (
            getattr(request, 'tenant_db_alias', '')
            or get_current_tenant_db_alias()
            or ''
        ).strip()

        tenant_id = normalize_tenant_id(
            getattr(request, 'tenant_id', '')
            or request.session.get('tenant_id', '')
            or (alias[len('tenant_'):] if alias.startswith('tenant_') else '')
        )
        return alias, tenant_id

    def _maybe_emit_export_security_alert(self, request, response):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        if request.method != 'GET' or getattr(response, 'status_code', 200) >= 400:
            return False
        if not self._is_export_request(request, response):
            return False

        tenant_alias, tenant_id = self._resolve_request_tenant(request)
        if not tenant_alias.startswith('tenant_') or not tenant_id:
            return False

        window_seconds = int(getattr(settings, 'SECURITY_EXPORT_WINDOW_SECONDS', 600))
        threshold = int(getattr(settings, 'SECURITY_EXPORT_ALERT_THRESHOLD', 5))
        if threshold < 1:
            return False

        counter_key = f"sec:export-burst:{tenant_id}:{user.pk}"
        alert_lock_key = f"{counter_key}:alerted"

        current_count = int(cache.get(counter_key) or 0) + 1
        cache.set(counter_key, current_count, timeout=window_seconds)

        if current_count < threshold:
            return False
        if cache.get(alert_lock_key):
            return False

        cache.set(alert_lock_key, 1, timeout=window_seconds)
        payload = {
            'alert_type': 'export_burst',
            'tenant_id': tenant_id,
            'username': user.username,
            'export_count': current_count,
            'window_seconds': window_seconds,
            'path': request.path,
            'ip_address': self._get_client_ip(request),
        }

        AuditLog.objects.using(tenant_alias).create(
            user=user,
            tenant_id=tenant_id,
            action='security_alert',
            target_model='ExportActivity',
            target_pk=str(user.pk),
            before_data={
                'threshold': threshold,
                'window_seconds': window_seconds,
            },
            after_data=payload,
            ip_address=payload['ip_address'],
            device_type=self._classify_device(request.META.get('HTTP_USER_AGENT') or ''),
            browser=self._classify_browser(request.META.get('HTTP_USER_AGENT') or ''),
            geo_location=self._resolve_geo_hint(request),
            request_path=request.path,
        )
        try:
            publish_tenant_event(
                tenant_id=tenant_id,
                topic='security',
                event='security.alert',
                payload=payload,
            )
        except Exception:
            # Avoid blocking exports if websocket channel layer is unavailable.
            pass
        return True

    def __call__(self, request):
        request_user = getattr(request, 'user', None)
        actor = request_user if request_user is not None and request_user.is_authenticated else None
        user_agent = (request.META.get('HTTP_USER_AGENT') or '').strip()
        tenant_id_for_audit = request.session.get('tenant_id', '')
        if not tenant_id_for_audit:
            current_alias = (get_current_tenant_db_alias() or '').strip()
            if current_alias.startswith('tenant_'):
                tenant_id_for_audit = current_alias[len('tenant_'):]
        set_request_audit_context(
            user=actor,
            tenant_id=tenant_id_for_audit,
            ip_address=self._get_client_ip(request),
            request_path=request.path,
            request_method=request.method,
            device_type=self._classify_device(user_agent),
            browser=self._classify_browser(user_agent),
            geo_location=self._resolve_geo_hint(request),
        )
        response = self.get_response(request)

        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            path = request.path or ''
            if not path.startswith('/static/') and not path.startswith('/media/') and not path.startswith('/admin/jsi18n/'):
                if (
                    getattr(request, 'user', None) is not None
                    and request.user.is_authenticated
                    and get_current_tenant_db_alias()
                ):
                    operation_text = f"{request.method} {path}"
                    OperationLog.objects.create(operation=operation_text, user=request.user)

                self._maybe_emit_export_security_alert(request, response)

        clear_request_audit_context()
        return response

    def process_exception(self, request, exception):
        clear_request_audit_context()
        return None


class UITranslationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._sorted_source_texts = sorted(UI_TRANSLATIONS.keys(), key=len, reverse=True)

    def __call__(self, request):
        response = self.get_response(request)

        content_type = (response.get('Content-Type') or '').lower() if hasattr(response, 'get') else ''
        language = (get_language() or 'ar').lower()
        if language.startswith('zh'):
            language = 'zh-hans'

        if language == 'ar' or 'text/html' not in content_type:
            return response

        raw_content = getattr(response, 'content', b'')
        if not raw_content:
            return response

        try:
            html = raw_content.decode(response.charset or 'utf-8')
        except Exception:
            return response

        translated_html = html
        for source_text in self._sorted_source_texts:
            target_text = UI_TRANSLATIONS.get(source_text, {}).get(language)
            if target_text:
                translated_html = translated_html.replace(source_text, target_text)

        if translated_html != html:
            response.content = translated_html.encode(response.charset or 'utf-8')

        return response
