from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .tenant_context import get_current_tenant_db_alias, get_current_tenant_id, set_current_tenant
from .tenant_database import ensure_tenant_connection, normalize_tenant_id
from .tenant_registry import get_cached_tenant_metadata


class TenantModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is None:
            return None

        tenant_id = normalize_tenant_id(request.POST.get('tenant_id') or request.session.get('tenant_id'))

        if not tenant_id or not username or not password:
            return None

        tenant_metadata = get_cached_tenant_metadata(tenant_id)
        if tenant_metadata is None or not tenant_metadata.get('is_active'):
            return None

        alias = ensure_tenant_connection(tenant_id)
        if not alias:
            return None

        set_current_tenant(tenant_id, alias)

        UserModel = get_user_model()
        try:
            user = UserModel.objects.using(alias).get(username=username)
        except UserModel.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None

    def get_user(self, user_id):
        UserModel = get_user_model()
        alias = get_current_tenant_db_alias()
        if not alias:
            tenant_id = normalize_tenant_id(get_current_tenant_id())
            if tenant_id:
                alias = ensure_tenant_connection(tenant_id)

        if not alias:
            return None

        try:
            return UserModel.objects.using(alias).get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
