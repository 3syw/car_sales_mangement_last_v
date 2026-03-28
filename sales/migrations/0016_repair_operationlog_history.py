from datetime import datetime, time

from django.db import migrations
from django.utils import timezone


def _table_names(schema_editor):
    return set(schema_editor.connection.introspection.table_names())


def _as_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, time.min)

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())

    return dt


def _create_log(OperationLog, db_alias, operation, created_at=None, user_id=None):
    log = OperationLog.objects.using(db_alias).create(operation=(operation or '')[:255], user_id=user_id)
    if created_at is not None:
        OperationLog.objects.using(db_alias).filter(pk=log.pk).update(created_at=created_at)


def forwards(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    tables = _table_names(schema_editor)
    if 'sales_operationlog' not in tables:
        return

    OperationLog = apps.get_model('sales', 'OperationLog')
    operation_logs = OperationLog.objects.using(db_alias)

    operation_logs.filter(operation__startswith='إضافة: operation log').delete()
    operation_logs.filter(operation__startswith='تعديل: operation log').delete()
    operation_logs.filter(operation__startswith='حذف: operation log').delete()

    operation_logs.filter(operation='تهيئة السجل التاريخي').delete()
    operation_logs.filter(operation__startswith='إنشاء حساب (سابق): ').delete()
    operation_logs.filter(operation__startswith='إضافة سيارة (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة عميل (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة عملية بيع (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة مصروف (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة سند تسديد (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة سند مالي (سابق) ID: ').delete()

    _create_log(OperationLog, db_alias, 'تهيئة السجل التاريخي')

    if 'auth_user' in tables:
        User = apps.get_model('auth', 'User')
        for user in User.objects.using(db_alias).all().only('id', 'username', 'date_joined').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إنشاء حساب (سابق): {user.username}",
                created_at=_as_datetime(user.date_joined),
                user_id=user.id,
            )

    if 'sales_car' in tables:
        Car = apps.get_model('sales', 'Car')
        for car in Car.objects.using(db_alias).all().only('id', 'created_at').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إضافة سيارة (سابق) ID: {car.id}",
                created_at=_as_datetime(car.created_at),
            )

    if 'sales_customer' in tables:
        Customer = apps.get_model('sales', 'Customer')
        for customer in Customer.objects.using(db_alias).all().only('id').order_by('id'):
            _create_log(OperationLog, db_alias, f"إضافة عميل (سابق) ID: {customer.id}")

    if 'sales_sale' in tables:
        Sale = apps.get_model('sales', 'Sale')
        for sale in Sale.objects.using(db_alias).all().only('id', 'sale_date').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إضافة عملية بيع (سابق) ID: {sale.id}",
                created_at=_as_datetime(sale.sale_date),
            )

    if 'sales_expense' in tables:
        Expense = apps.get_model('sales', 'Expense')
        for expense in Expense.objects.using(db_alias).all().only('id', 'date').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إضافة مصروف (سابق) ID: {expense.id}",
                created_at=_as_datetime(expense.date),
            )

    if 'sales_debtpayment' in tables:
        DebtPayment = apps.get_model('sales', 'DebtPayment')
        for payment in DebtPayment.objects.using(db_alias).all().only('id', 'created_at', 'payment_date').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إضافة سند تسديد (سابق) ID: {payment.id}",
                created_at=_as_datetime(payment.created_at) or _as_datetime(payment.payment_date),
            )

    if 'sales_financevoucher' in tables:
        FinanceVoucher = apps.get_model('sales', 'FinanceVoucher')
        for voucher in FinanceVoucher.objects.using(db_alias).all().only('id', 'created_at', 'voucher_date').order_by('id'):
            _create_log(
                OperationLog,
                db_alias,
                f"إضافة سند مالي (سابق) ID: {voucher.id}",
                created_at=_as_datetime(voucher.created_at) or _as_datetime(voucher.voucher_date),
            )


def backwards(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    if 'sales_operationlog' not in _table_names(schema_editor):
        return

    OperationLog = apps.get_model('sales', 'OperationLog')
    operation_logs = OperationLog.objects.using(db_alias)
    operation_logs.filter(operation='تهيئة السجل التاريخي').delete()
    operation_logs.filter(operation__startswith='إنشاء حساب (سابق): ').delete()
    operation_logs.filter(operation__startswith='إضافة سيارة (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة عميل (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة عملية بيع (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة مصروف (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة سند تسديد (سابق) ID: ').delete()
    operation_logs.filter(operation__startswith='إضافة سند مالي (سابق) ID: ').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0015_backfill_operationlog_history'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
