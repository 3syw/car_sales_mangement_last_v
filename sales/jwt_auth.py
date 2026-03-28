from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings

from .tenant_context import set_current_tenant
from .tenant_database import ensure_tenant_connection, normalize_tenant_id


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        token_tenant_id = normalize_tenant_id(validated_token.get('tenant_id'))
        header_tenant_id = normalize_tenant_id(
            request.headers.get('X-Tenant-ID')
            or request.META.get('HTTP_X_TENANT_ID')
        )

        if not token_tenant_id:
            raise AuthenticationFailed('التوكن لا يحتوي على بيئة معرض صالحة.')

        if header_tenant_id and header_tenant_id != token_tenant_id:
            raise AuthenticationFailed('عدم تطابق بيئة المعرض بين التوكن والترويسة.')

        tenant_id = token_tenant_id

        tenant_alias = ensure_tenant_connection(tenant_id)
        if not tenant_alias:
            raise AuthenticationFailed('تعذر الوصول إلى قاعدة بيانات المعرض.')

        token_tenant_alias = (validated_token.get('tenant_alias') or '').strip()
        if token_tenant_alias and token_tenant_alias != tenant_alias:
            raise AuthenticationFailed('التوكن يحتوي على معرف قاعدة بيانات معرض غير صالح.')

        user_model = get_user_model()
        user_id = validated_token.get(api_settings.USER_ID_CLAIM)
        if user_id is None:
            raise AuthenticationFailed('التوكن لا يحتوي على معرف مستخدم صالح.')

        try:
            tenant_user = user_model.objects.using(tenant_alias).get(pk=user_id)
        except user_model.DoesNotExist as exc:
            raise AuthenticationFailed('المستخدم غير موجود في بيئة المعرض المحددة.') from exc

        set_current_tenant(tenant_id, tenant_alias)
        request.tenant_id = tenant_id
        request.tenant_db_alias = tenant_alias
        return (tenant_user, validated_token)