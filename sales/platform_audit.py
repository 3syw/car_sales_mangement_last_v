from .models import GlobalAuditLog
from .tenant_database import normalize_tenant_id, tenant_db_path


def get_tenant_db_size_bytes(tenant_id):
    normalized = normalize_tenant_id(tenant_id)
    if not normalized:
        return 0

    db_file = tenant_db_path(normalized)
    if not db_file.exists():
        return 0

    return int(db_file.stat().st_size)


def write_platform_audit(event_type, tenant_id='', actor_username='', notes=''):
    normalized = normalize_tenant_id(tenant_id)
    db_size = get_tenant_db_size_bytes(normalized)

    GlobalAuditLog.objects.using('default').create(
        tenant_id=normalized,
        actor_username=(actor_username or '')[:150],
        event_type=event_type,
        data_size_bytes=db_size,
        notes=(notes or '')[:255],
    )
