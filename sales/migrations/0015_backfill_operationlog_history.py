from django.db import migrations


def _table_names(schema_editor):
    return set(schema_editor.connection.introspection.table_names())


def seed_previous_operations(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    tables = _table_names(schema_editor)
    if 'sales_operationlog' not in tables:
        return

    OperationLog = apps.get_model('sales', 'OperationLog')
    operation_logs = OperationLog.objects.using(db_alias)

    marker_exists = operation_logs.filter(operation='تهيئة السجل التاريخي').exists()
    if marker_exists:
        return

    operation_logs.create(operation='تهيئة السجل التاريخي')

    if 'auth_user' in tables:
        User = apps.get_model('auth', 'User')
        for user in User.objects.using(db_alias).all().only('id', 'username'):
            operation_logs.create(operation=f"إنشاء حساب (سابق): {user.username}"[:255])

    if 'sales_car' in tables:
        Car = apps.get_model('sales', 'Car')
        for car in Car.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة سيارة (سابق) ID: {car.id}"[:255])

    if 'sales_customer' in tables:
        Customer = apps.get_model('sales', 'Customer')
        for customer in Customer.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة عميل (سابق) ID: {customer.id}"[:255])

    if 'sales_sale' in tables:
        Sale = apps.get_model('sales', 'Sale')
        for sale in Sale.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة عملية بيع (سابق) ID: {sale.id}"[:255])

    if 'sales_expense' in tables:
        Expense = apps.get_model('sales', 'Expense')
        for expense in Expense.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة مصروف (سابق) ID: {expense.id}"[:255])

    if 'sales_debtpayment' in tables:
        DebtPayment = apps.get_model('sales', 'DebtPayment')
        for payment in DebtPayment.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة سند تسديد (سابق) ID: {payment.id}"[:255])

    if 'sales_financevoucher' in tables:
        FinanceVoucher = apps.get_model('sales', 'FinanceVoucher')
        for voucher in FinanceVoucher.objects.using(db_alias).all().only('id'):
            operation_logs.create(operation=f"إضافة سند مالي (سابق) ID: {voucher.id}"[:255])


def remove_seeded_operations(apps, schema_editor):
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
        ('sales', '0014_operationlog'),
    ]

    operations = [
        migrations.RunPython(seed_previous_operations, remove_seeded_operations),
    ]
