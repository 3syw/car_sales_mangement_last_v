from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connections


TENANT_DB_DIR = Path(settings.BASE_DIR) / 'tenant_dbs'


def normalize_tenant_id(raw_tenant_id):
    return (raw_tenant_id or '').strip().lower()


def tenant_db_alias(tenant_id):
    return f"tenant_{normalize_tenant_id(tenant_id)}"


def tenant_db_path(tenant_id):
    normalized = normalize_tenant_id(tenant_id)
    return TENANT_DB_DIR / f"{normalized}.sqlite3"


def ensure_tenant_connection(tenant_id):
    normalized = normalize_tenant_id(tenant_id)
    if not normalized:
        return None

    TENANT_DB_DIR.mkdir(parents=True, exist_ok=True)
    alias = tenant_db_alias(normalized)
    db_path = tenant_db_path(normalized)

    if alias not in connections.databases:
        default_config = connections.databases.get('default', {}).copy()
        default_config['NAME'] = str(db_path)
        default_config['ENGINE'] = 'django.db.backends.sqlite3'
        connections.databases[alias] = default_config

    return alias


def migrate_tenant_database(tenant_id):
    alias = ensure_tenant_connection(tenant_id)
    if not alias:
        return None

    call_command('migrate', database=alias, interactive=False, verbosity=0)
    return alias
