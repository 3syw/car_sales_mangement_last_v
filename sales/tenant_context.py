from threading import local

_state = local()


def set_current_tenant(tenant_id=None, db_alias=None):
    _state.tenant_id = tenant_id
    _state.db_alias = db_alias


def clear_current_tenant():
    _state.tenant_id = None
    _state.db_alias = None


def get_current_tenant_id():
    return getattr(_state, 'tenant_id', None)


def get_current_tenant_db_alias():
    return getattr(_state, 'db_alias', None)
