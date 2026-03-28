from django.contrib.auth.hashers import check_password
from django.core.cache import cache

from .models import PlatformTenant
from .tenant_database import normalize_tenant_id

TENANT_CACHE_TTL_SECONDS = 300


def _tenant_cache_key(tenant_id):
    return f"platform_tenant:{tenant_id}"


def get_cached_tenant_metadata(tenant_id):
    normalized_id = normalize_tenant_id(tenant_id)
    if not normalized_id:
        return None

    cache_key = _tenant_cache_key(normalized_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    tenant = PlatformTenant.objects.using('default').filter(tenant_id=normalized_id).values(
        'tenant_id', 'name', 'is_active', 'is_deleted', 'access_key_hash'
    ).first()

    cache.set(cache_key, tenant, TENANT_CACHE_TTL_SECONDS)
    return tenant


def invalidate_tenant_cache(tenant_id):
    normalized_id = normalize_tenant_id(tenant_id)
    if normalized_id:
        cache.delete(_tenant_cache_key(normalized_id))


def is_valid_tenant_access_key(tenant_metadata, raw_key):
    if not tenant_metadata or not tenant_metadata.get('is_active') or tenant_metadata.get('is_deleted'):
        return False

    access_key_hash = tenant_metadata.get('access_key_hash')
    if not access_key_hash:
        return False

    return check_password(raw_key or '', access_key_hash)
