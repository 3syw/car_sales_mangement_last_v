from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import Car, CarDocument, CarMaintenance, FinanceVoucher, PlatformTenant, Sale
from .tenant_context import get_current_tenant_id
from .tenant_database import normalize_tenant_id, ensure_tenant_connection


User = get_user_model()


def _get_active_tenant():
    tenant_id = normalize_tenant_id(get_current_tenant_id())
    if not tenant_id:
        return None, None

    tenant = PlatformTenant.objects.using('default').filter(tenant_id=tenant_id, is_active=True).first()
    if tenant is None:
        return None, None

    alias = ensure_tenant_connection(tenant_id)
    return tenant, alias


def enforce_user_quota_or_raise(extra_users=1):
    tenant, alias = _get_active_tenant()
    if tenant is None or alias is None:
        return

    current_users = User.objects.using(alias).count()
    if current_users + int(extra_users) > tenant.max_users:
        raise ValidationError(f"تم تجاوز الحد الأقصى للمستخدمين ({tenant.max_users}).")


def enforce_car_quota_or_raise(extra_cars=1):
    tenant, alias = _get_active_tenant()
    if tenant is None or alias is None:
        return

    current_cars = Car.objects.using(alias).count()
    if current_cars + int(extra_cars) > tenant.max_cars:
        raise ValidationError(f"تم تجاوز الحد الأقصى للسيارات ({tenant.max_cars}).")


def _safe_file_size(file_field):
    if not file_field:
        return 0

    try:
        if hasattr(file_field, 'size') and file_field.size is not None:
            return int(file_field.size)
    except Exception:
        pass

    return 0


def _current_storage_usage_bytes(alias):
    total = 0
    for car in Car.objects.using(alias).all().only('image', 'contract_image'):
        total += _safe_file_size(car.image)
        total += _safe_file_size(car.contract_image)

    for sale in Sale.objects.using(alias).all().only('sale_contract_image'):
        total += _safe_file_size(sale.sale_contract_image)

    for item in CarMaintenance.objects.using(alias).all().only('invoice_image'):
        total += _safe_file_size(item.invoice_image)

    for item in CarDocument.objects.using(alias).all().only('file'):
        total += _safe_file_size(item.file)

    for voucher in FinanceVoucher.objects.using(alias).all().only('supporting_document'):
        total += _safe_file_size(voucher.supporting_document)

    return total


def enforce_storage_quota_or_raise(additional_bytes=0):
    tenant, alias = _get_active_tenant()
    if tenant is None or alias is None:
        return

    max_bytes = int(tenant.max_storage_mb) * 1024 * 1024
    current_bytes = _current_storage_usage_bytes(alias)
    if current_bytes + int(additional_bytes) > max_bytes:
        raise ValidationError(f"تم تجاوز الحد الأقصى لمساحة التخزين ({tenant.max_storage_mb} MB).")
