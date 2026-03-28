from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from threading import local
from decimal import Decimal
from datetime import date, datetime

from .audit import get_current_user, get_current_audit_context
from .accounting import delete_journal_entry_for_voucher, sync_journal_entry_for_voucher
from .financial_governance import enforce_open_period_or_raise
from .models import (
    OperationLog,
    AuditLog,
    AccountLedger,
    Car,
    CarHistory,
    Sale,
    JournalEntryLine,
    CustomerAccount,
    PlatformTenant,
    Expense,
    GeneralExpense,
    DebtPayment,
    FinanceVoucher,
    CarMaintenance,
    InventoryTransaction,
    Invoice,
    InvoiceLine,
    Notification,
    SupplierInvoice,
    SupplierPayment,
)
from .realtime import publish_tenant_event
from .tenant_context import get_current_tenant_db_alias
from .tenant_registry import invalidate_tenant_cache

_state = local()
_audit_state = local()
SALE_DOWN_PAYMENT_MARKER = '[SALE_DOWN_PAYMENT]'

_UNTRACKED_MODEL_LABELS = {
    'sales.operationlog',
    'sales.auditlog',
    'sales.accountledger',
    'sales.customeraccount',
    'sales.carhistory',
    'sales.platformtenant',
    'sales.globalauditlog',
    'sales.tenantbackuprecord',
    'sales.tenantmigrationrecord',
    'sales.journalentry',
    'sales.journalentryline',
}

_LOCKED_FINANCIAL_MODELS = {
    Sale: 'sale_date',
    DebtPayment: 'payment_date',
    FinanceVoucher: 'voucher_date',
    CarMaintenance: 'operation_date',
    SupplierInvoice: 'invoice_date',
    SupplierPayment: 'payment_date',
    Invoice: 'invoice_date',
    Expense: 'date',
    GeneralExpense: 'expense_date',
}


def _active_tenant_alias():
    alias = (get_current_tenant_db_alias() or '').strip()
    if alias.startswith('tenant_'):
        return alias
    return ''


def _resolve_tenant_alias(instance=None, using=''):
    alias = _active_tenant_alias()
    if alias:
        return alias

    alias = (using or '').strip()
    if alias.startswith('tenant_'):
        return alias

    state_db = (getattr(getattr(instance, '_state', None), 'db', '') or '').strip()
    if state_db.startswith('tenant_'):
        return state_db

    return ''


def _get_safe_user(user=None):
    if user is not None and getattr(user, 'is_authenticated', False):
        return user

    current_user = get_current_user()
    if current_user is not None and getattr(current_user, 'is_authenticated', False):
        return current_user

    return None


def _write_log(message, user=None, alias=''):
    message = (message or '').strip()
    if not message:
        return

    resolved_alias = _resolve_tenant_alias(using=alias)
    if not resolved_alias:
        return

    if getattr(_state, 'is_writing', False):
        return

    user_obj = _get_safe_user(user)
    user_id = None
    if user_obj is not None and getattr(user_obj._state, 'db', None) == resolved_alias:
        user_id = user_obj.pk

    _state.is_writing = True
    try:
        OperationLog.objects.using(resolved_alias).create(operation=message[:255], user_id=user_id)
    finally:
        _state.is_writing = False


def _emit_realtime_event(*, alias, topic, event, payload):
    resolved_alias = (alias or '').strip()
    if not resolved_alias.startswith('tenant_'):
        return

    tenant_id = resolved_alias[len('tenant_'):]
    transaction.on_commit(
        lambda: publish_tenant_event(
            tenant_id=tenant_id,
            topic=topic,
            event=event,
            payload=payload,
        ),
        using=resolved_alias,
    )


def _is_tracked_model(sender):
    return sender._meta.app_label == 'sales' and sender._meta.label_lower not in _UNTRACKED_MODEL_LABELS


def _extract_operation_date(instance, field_name):
    value = getattr(instance, field_name, None)
    if isinstance(value, datetime):
        return value.date()
    return value


def _enforce_financial_day_lock(sender, instance, is_delete=False, using=''):
    field_name = _LOCKED_FINANCIAL_MODELS.get(sender)
    if not field_name:
        return

    alias = _resolve_tenant_alias(instance=instance, using=using)
    if not alias:
        return

    locked_operation_date = _extract_operation_date(instance, field_name)

    if not is_delete and instance.pk:
        old_instance = sender.objects.using(alias).filter(pk=instance.pk).only(field_name).first()
        if old_instance is not None:
            locked_operation_date = _extract_operation_date(old_instance, field_name)

    if locked_operation_date is None:
        return

    if is_delete:
        action_label = 'حذف عملية ضمن يومية مغلقة'
    elif instance.pk:
        action_label = 'تعديل عملية ضمن يومية مغلقة'
    else:
        action_label = 'إضافة عملية بتاريخ يومية مغلقة'

    enforce_open_period_or_raise(locked_operation_date, alias=alias, action_label=action_label)


@receiver(pre_save, dispatch_uid='sales_financial_lock_pre_save')
def enforce_financial_lock_before_save(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    _enforce_financial_day_lock(sender, instance, is_delete=False, using=kwargs.get('using', ''))


@receiver(pre_delete, dispatch_uid='sales_financial_lock_pre_delete')
def enforce_financial_lock_before_delete(sender, instance, **kwargs):
    _enforce_financial_day_lock(sender, instance, is_delete=True, using=kwargs.get('using', ''))


@receiver(post_save, dispatch_uid='sales_operationlog_post_save')
def log_model_save(sender, instance, created, **kwargs):
    if kwargs.get('raw'):
        return

    if not _is_tracked_model(sender):
        return

    action = 'إضافة' if created else 'تعديل'
    label = sender._meta.verbose_name or sender.__name__
    _write_log(f"{action}: {label} (ID: {instance.pk})", alias=getattr(instance._state, 'db', ''))


@receiver(post_delete, dispatch_uid='sales_operationlog_post_delete')
def log_model_delete(sender, instance, **kwargs):
    if not _is_tracked_model(sender):
        return

    label = sender._meta.verbose_name or sender.__name__
    _write_log(f"حذف: {label} (ID: {instance.pk})", alias=getattr(instance._state, 'db', ''))


_REALTIME_MODELS = {Car, Sale, DebtPayment, FinanceVoucher, AuditLog, Notification}


@receiver(post_save, dispatch_uid='sales_realtime_post_save')
def broadcast_model_save(sender, instance, created, **kwargs):
    if kwargs.get('raw') or sender not in _REALTIME_MODELS:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    topic = sender._meta.model_name
    payload = {
        'model': sender._meta.label_lower,
        'pk': str(instance.pk),
        'action': 'created' if created else 'updated',
    }
    if sender is AuditLog:
        payload['audit_action'] = instance.action
        payload['target_model'] = instance.target_model
        payload['target_pk'] = instance.target_pk
    if sender is Notification:
        payload['message'] = instance.message
        payload['is_read'] = instance.is_read

    _emit_realtime_event(alias=alias, topic=topic, event='model.changed', payload=payload)


@receiver(post_delete, dispatch_uid='sales_realtime_post_delete')
def broadcast_model_delete(sender, instance, **kwargs):
    if sender not in _REALTIME_MODELS:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _emit_realtime_event(
        alias=alias,
        topic=sender._meta.model_name,
        event='model.deleted',
        payload={
            'model': sender._meta.label_lower,
            'pk': str(instance.pk),
            'action': 'deleted',
        },
    )


@receiver(post_save, sender=FinanceVoucher, dispatch_uid='sales_sync_voucher_journal_entry')
def sync_voucher_journal_entry(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias or not alias.startswith('tenant_'):
        return

    if instance.voucher_type == 'receipt' and SALE_DOWN_PAYMENT_MARKER in (instance.reason or ''):
        return

    user_obj = _get_safe_user()
    user_id = None
    if user_obj is not None and getattr(user_obj._state, 'db', None) == alias:
        user_id = user_obj.pk

    sync_journal_entry_for_voucher(instance, alias=alias, created_by_id=user_id)


@receiver(post_delete, sender=FinanceVoucher, dispatch_uid='sales_delete_voucher_journal_entry')
def delete_voucher_journal_entry(sender, instance, **kwargs):
    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias or not alias.startswith('tenant_'):
        return

    delete_journal_entry_for_voucher(instance.pk, alias=alias)


def _resolve_ledger_reference(entry):
    source_model = (entry.source_model or '').strip().lower()
    if source_model == 'sale':
        return AccountLedger.REFERENCE_SALE
    if source_model == 'financevoucher':
        return AccountLedger.REFERENCE_VOUCHER
    if source_model == 'carmaintenance':
        return AccountLedger.REFERENCE_MAINTENANCE
    if source_model in {'expense', 'generalexpense'}:
        return AccountLedger.REFERENCE_EXPENSE
    return AccountLedger.REFERENCE_OTHER


@receiver(post_save, sender=JournalEntryLine, dispatch_uid='sales_create_account_ledger_row')
def create_account_ledger_row(sender, instance, created, **kwargs):
    if kwargs.get('raw') or not created:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias or not alias.startswith('tenant_'):
        return

    debit_value = instance.debit or Decimal('0')
    credit_value = instance.credit or Decimal('0')
    if debit_value == Decimal('0') and credit_value == Decimal('0'):
        return

    with transaction.atomic(using=alias):
        last_row = (
            AccountLedger.objects.using(alias)
            .select_for_update()
            .filter(account_id=instance.account_id)
            .order_by('-transaction_date', '-id')
            .first()
        )
        previous_balance = last_row.balance_after if last_row is not None else Decimal('0')
        next_balance = previous_balance + debit_value - credit_value

        AccountLedger.objects.using(alias).get_or_create(
            journal_line_id=instance.pk,
            defaults={
                'account_id': instance.account_id,
                'transaction_date': instance.entry.entry_date,
                'debit': debit_value,
                'credit': credit_value,
                'balance_after': next_balance,
                'reference_type': _resolve_ledger_reference(instance.entry),
                'reference_id': instance.entry.source_pk or '',
                'notes': (instance.line_description or '')[:255],
            },
        )


def _recalculate_customer_account(customer_id, alias):
    if not customer_id:
        return

    aggregates = Sale.objects.using(alias).filter(customer_id=customer_id).aggregate(
        total_debt=Sum('sale_price'),
        total_paid=Sum('amount_paid'),
    )
    total_debt = aggregates['total_debt'] or Decimal('0')
    total_paid = aggregates['total_paid'] or Decimal('0')
    current_balance = total_debt - total_paid

    last_payment_date = (
        DebtPayment.objects.using(alias)
        .filter(sale__customer_id=customer_id)
        .order_by('-payment_date', '-id')
        .values_list('payment_date', flat=True)
        .first()
    )

    CustomerAccount.objects.using(alias).update_or_create(
        customer_id=customer_id,
        defaults={
            'total_debt': total_debt,
            'total_paid': total_paid,
            'current_balance': current_balance,
            'last_payment_date': last_payment_date,
        },
    )


@receiver(post_save, sender=Sale, dispatch_uid='sales_sync_customer_account_on_sale_save')
def sync_customer_account_on_sale_save(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _recalculate_customer_account(instance.customer_id, alias)


@receiver(post_delete, sender=Sale, dispatch_uid='sales_sync_customer_account_on_sale_delete')
def sync_customer_account_on_sale_delete(sender, instance, **kwargs):
    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _recalculate_customer_account(instance.customer_id, alias)


def _payment_customer_id(payment_instance, alias):
    if not payment_instance.sale_id:
        return None

    return (
        Sale.objects.using(alias)
        .filter(pk=payment_instance.sale_id)
        .values_list('customer_id', flat=True)
        .first()
    )


@receiver(post_save, sender=DebtPayment, dispatch_uid='sales_sync_customer_account_on_payment_save')
def sync_customer_account_on_payment_save(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    customer_id = _payment_customer_id(instance, alias)
    _recalculate_customer_account(customer_id, alias)


@receiver(post_delete, sender=DebtPayment, dispatch_uid='sales_sync_customer_account_on_payment_delete')
def sync_customer_account_on_payment_delete(sender, instance, **kwargs):
    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    customer_id = _payment_customer_id(instance, alias)
    _recalculate_customer_account(customer_id, alias)


def _sync_supplier_invoice_totals(invoice_id, alias):
    if not invoice_id:
        return

    total_paid = (
        SupplierPayment.objects.using(alias)
        .filter(invoice_id=invoice_id)
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )
    invoice = SupplierInvoice.objects.using(alias).filter(pk=invoice_id).first()
    if invoice is None:
        return

    invoice.paid_amount = total_paid
    invoice.save(using=alias, update_fields=['paid_amount', 'status'])


@receiver(post_save, sender=SupplierPayment, dispatch_uid='sales_sync_supplier_invoice_on_payment_save')
def sync_supplier_invoice_on_payment_save(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _sync_supplier_invoice_totals(instance.invoice_id, alias)


@receiver(post_delete, sender=SupplierPayment, dispatch_uid='sales_sync_supplier_invoice_on_payment_delete')
def sync_supplier_invoice_on_payment_delete(sender, instance, **kwargs):
    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _sync_supplier_invoice_totals(instance.invoice_id, alias)


def _recalculate_invoice_totals(invoice_id, alias):
    if not invoice_id:
        return

    invoice = Invoice.objects.using(alias).select_related('tax_rate').filter(pk=invoice_id).first()
    if invoice is None:
        return

    subtotal = (
        InvoiceLine.objects.using(alias)
        .filter(invoice_id=invoice_id)
        .aggregate(total=Sum('line_total'))['total']
        or Decimal('0')
    )
    tax_amount = Decimal('0')
    if invoice.tax_rate_id and invoice.tax_rate and invoice.tax_rate.is_active:
        tax_amount = (
            subtotal * (invoice.tax_rate.rate_percent or Decimal('0')) / Decimal('100')
        ).quantize(Decimal('0.01'))

    Invoice.objects.using(alias).filter(pk=invoice_id).update(
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=subtotal + tax_amount,
    )


@receiver(post_save, sender=InvoiceLine, dispatch_uid='sales_recalculate_invoice_totals_on_line_save')
def recalculate_invoice_totals_on_line_save(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _recalculate_invoice_totals(instance.invoice_id, alias)


@receiver(post_delete, sender=InvoiceLine, dispatch_uid='sales_recalculate_invoice_totals_on_line_delete')
def recalculate_invoice_totals_on_line_delete(sender, instance, **kwargs):
    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    _recalculate_invoice_totals(instance.invoice_id, alias)


@receiver(post_save, sender=Car, dispatch_uid='sales_create_car_history_on_car_create')
def create_car_history_on_car_create(sender, instance, created, **kwargs):
    if kwargs.get('raw') or not created:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    CarHistory.objects.using(alias).create(
        car_id=instance.pk,
        event_type=CarHistory.EVENT_PURCHASE,
        event_date=timezone.localdate(),
        reference_type='Car',
        reference_id=str(instance.pk),
        notes='إضافة سيارة جديدة إلى المخزون.',
    )

    InventoryTransaction.objects.using(alias).create(
        car_id=instance.pk,
        transaction_type=InventoryTransaction.TYPE_PURCHASE,
        transaction_date=timezone.localdate(),
        cost=instance.total_cost_price or Decimal('0'),
        reference_type='Car',
        reference_id=str(instance.pk),
        notes='إدخال سيارة جديدة للمخزون.',
    )


@receiver(post_save, sender=Sale, dispatch_uid='sales_create_car_history_on_sale')
def create_car_history_on_sale(sender, instance, created, **kwargs):
    if kwargs.get('raw') or not created:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    CarHistory.objects.using(alias).create(
        car_id=instance.car_id,
        event_type=CarHistory.EVENT_SOLD,
        event_date=timezone.localdate(),
        reference_type='Sale',
        reference_id=str(instance.pk),
        notes=f"بيع السيارة للعميل {instance.customer.name}.",
    )

    InventoryTransaction.objects.using(alias).create(
        car_id=instance.car_id,
        transaction_type=InventoryTransaction.TYPE_SALE,
        transaction_date=timezone.localdate(),
        cost=instance.car.total_cost_price or Decimal('0'),
        reference_type='Sale',
        reference_id=str(instance.pk),
        notes='إخراج السيارة من المخزون نتيجة البيع.',
    )


@receiver(post_save, sender=CarMaintenance, dispatch_uid='sales_create_car_history_on_maintenance')
def create_car_history_on_maintenance(sender, instance, created, **kwargs):
    if kwargs.get('raw') or not created:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    CarHistory.objects.using(alias).create(
        car_id=instance.car_id,
        event_type=CarHistory.EVENT_MAINTENANCE,
        event_date=instance.operation_date,
        reference_type='CarMaintenance',
        reference_id=str(instance.pk),
        notes=f"صيانة بقيمة {instance.amount}.",
    )

    InventoryTransaction.objects.using(alias).create(
        car_id=instance.car_id,
        transaction_type=InventoryTransaction.TYPE_MAINTENANCE,
        transaction_date=instance.operation_date,
        cost=instance.amount or Decimal('0'),
        reference_type='CarMaintenance',
        reference_id=str(instance.pk),
        notes='تكلفة صيانة مرتبطة بالسيارة.',
    )


def _serialize_instance(instance):
    payload = {}
    for field in instance._meta.fields:
        if field.is_relation and hasattr(field, 'attname'):
            value = getattr(instance, field.attname, None)
        else:
            value = getattr(instance, field.name, None)

        if isinstance(value, Decimal):
            payload[field.name] = str(value)
        elif isinstance(value, (date, datetime)):
            payload[field.name] = value.isoformat()
        elif hasattr(value, 'name'):
            payload[field.name] = value.name
        else:
            payload[field.name] = value

    return payload


def _is_sensitive_audit_model(sender):
    return sender in {Car, Sale}


def _get_previous_payload(sender, pk, alias=''):
    if not pk:
        return None

    resolved_alias = (alias or '').strip()
    queryset = sender.objects.using(resolved_alias) if resolved_alias else sender.objects
    old_instance = queryset.filter(pk=pk).first()
    if old_instance is None:
        return None

    return _serialize_instance(old_instance)


def _stash_before_data(sender, instance, before_payload):
    model_key = f"{sender._meta.label_lower}:{instance.pk or 'new'}"
    if not hasattr(_audit_state, 'before_data'):
        _audit_state.before_data = {}
    _audit_state.before_data[model_key] = before_payload


def _pop_before_data(sender, instance):
    model_key = f"{sender._meta.label_lower}:{instance.pk or 'new'}"
    cached = getattr(_audit_state, 'before_data', {})
    return cached.pop(model_key, None)


@receiver(pre_save, dispatch_uid='sales_sensitive_audit_pre_save')
def capture_sensitive_before_state(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return

    if not _is_sensitive_audit_model(sender):
        return

    if not instance.pk:
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    before_payload = _get_previous_payload(sender, instance.pk, alias=alias)
    _stash_before_data(sender, instance, before_payload)


@receiver(post_save, dispatch_uid='sales_sensitive_audit_post_save')
def write_sensitive_audit_save(sender, instance, created, **kwargs):
    if kwargs.get('raw'):
        return

    if not _is_sensitive_audit_model(sender):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    before_payload = None if created else _pop_before_data(sender, instance)
    after_payload = _serialize_instance(instance)
    context = get_current_audit_context()
    user = context.get('user')
    user_id = user.pk if user is not None and getattr(user._state, 'db', None) == alias else None

    AuditLog.objects.using(alias).create(
        user_id=user_id,
        tenant_id=context['tenant_id'] or alias.replace('tenant_', ''),
        action='create' if created else 'update',
        target_model=sender.__name__,
        target_pk=str(instance.pk or ''),
        before_data=before_payload,
        after_data=after_payload,
        ip_address=context['ip_address'],
        device_type=context.get('device_type', ''),
        browser=context.get('browser', ''),
        geo_location=context.get('geo_location', ''),
        request_path=context['request_path'],
    )


@receiver(post_delete, dispatch_uid='sales_sensitive_audit_post_delete')
def write_sensitive_audit_delete(sender, instance, **kwargs):
    if not _is_sensitive_audit_model(sender):
        return

    alias = _resolve_tenant_alias(instance=instance, using=kwargs.get('using', ''))
    if not alias:
        return

    context = get_current_audit_context()
    user = context.get('user')
    user_id = user.pk if user is not None and getattr(user._state, 'db', None) == alias else None
    AuditLog.objects.using(alias).create(
        user_id=user_id,
        tenant_id=context['tenant_id'] or alias.replace('tenant_', ''),
        action='delete',
        target_model=sender.__name__,
        target_pk=str(instance.pk or ''),
        before_data=_serialize_instance(instance),
        after_data=None,
        ip_address=context['ip_address'],
        device_type=context.get('device_type', ''),
        browser=context.get('browser', ''),
        geo_location=context.get('geo_location', ''),
        request_path=context['request_path'],
    )


@receiver(user_logged_in, dispatch_uid='sales_operationlog_user_logged_in')
def log_user_login(sender, request, user, **kwargs):
    _write_log('تسجيل دخول', user=user)


@receiver(user_logged_out, dispatch_uid='sales_operationlog_user_logged_out')
def log_user_logout(sender, request, user, **kwargs):
    _write_log('تسجيل خروج', user=user)


@receiver(user_login_failed, dispatch_uid='sales_operationlog_user_login_failed')
def log_user_login_failed(sender, credentials, request, **kwargs):
    _write_log('فشل تسجيل دخول')


def _connect_auth_user_signals():
    User = get_user_model()

    @receiver(post_save, sender=User, dispatch_uid='sales_operationlog_auth_user_save')
    def log_user_account_save(sender, instance, created, **kwargs):
        action = 'إنشاء حساب' if created else 'تعديل حساب'
        _write_log(action)

    @receiver(post_delete, sender=User, dispatch_uid='sales_operationlog_auth_user_delete')
    def log_user_account_delete(sender, instance, **kwargs):
        _write_log('حذف حساب')


_connect_auth_user_signals()


@receiver(post_save, sender=PlatformTenant, dispatch_uid='sales_platform_tenant_post_save')
def clear_platform_tenant_cache_on_save(sender, instance, **kwargs):
    invalidate_tenant_cache(instance.tenant_id)


@receiver(post_delete, sender=PlatformTenant, dispatch_uid='sales_platform_tenant_post_delete')
def clear_platform_tenant_cache_on_delete(sender, instance, **kwargs):
    invalidate_tenant_cache(instance.tenant_id)
