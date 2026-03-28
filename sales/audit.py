from threading import local

from django.contrib.auth import get_user_model

_thread_local = local()


def set_current_user(user):
    if user is not None and getattr(user, 'is_authenticated', False):
        _thread_local.user_id = user.pk
        return

    _thread_local.user_id = None


def set_request_audit_context(
    user=None,
    tenant_id='',
    ip_address='',
    request_path='',
    request_method='',
    device_type='',
    browser='',
    geo_location='',
):
    set_current_user(user)
    _thread_local.tenant_id = (tenant_id or '').strip()
    _thread_local.ip_address = (ip_address or '').strip()
    _thread_local.request_path = (request_path or '').strip()
    _thread_local.request_method = (request_method or '').strip().upper()
    _thread_local.device_type = (device_type or '').strip()
    _thread_local.browser = (browser or '').strip()
    _thread_local.geo_location = (geo_location or '').strip()


def clear_request_audit_context():
    set_current_user(None)
    _thread_local.tenant_id = ''
    _thread_local.ip_address = ''
    _thread_local.request_path = ''
    _thread_local.request_method = ''
    _thread_local.device_type = ''
    _thread_local.browser = ''
    _thread_local.geo_location = ''


def get_current_audit_context():
    return {
        'user': get_current_user(),
        'tenant_id': getattr(_thread_local, 'tenant_id', '') or '',
        'ip_address': getattr(_thread_local, 'ip_address', '') or '',
        'request_path': getattr(_thread_local, 'request_path', '') or '',
        'request_method': getattr(_thread_local, 'request_method', '') or '',
        'device_type': getattr(_thread_local, 'device_type', '') or '',
        'browser': getattr(_thread_local, 'browser', '') or '',
        'geo_location': getattr(_thread_local, 'geo_location', '') or '',
    }


def get_current_user():
    user_id = getattr(_thread_local, 'user_id', None)
    if not user_id:
        return None

    User = get_user_model()
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return None
