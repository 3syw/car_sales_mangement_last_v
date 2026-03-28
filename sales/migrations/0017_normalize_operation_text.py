from django.db import migrations


def _has_operationlog_table(schema_editor):
    return 'sales_operationlog' in set(schema_editor.connection.introspection.table_names())


def forwards(apps, schema_editor):
    if not _has_operationlog_table(schema_editor):
        return

    OperationLog = apps.get_model('sales', 'OperationLog')
    logs = OperationLog.objects.using(schema_editor.connection.alias)

    for log in logs.filter(operation__startswith='إنشاء حساب (سابق): '):
        logs.filter(pk=log.pk).update(operation='إنشاء حساب (سابق)')

    for log in logs.filter(operation__startswith='إنشاء حساب: '):
        logs.filter(pk=log.pk).update(operation='إنشاء حساب')

    for log in logs.filter(operation__startswith='تعديل حساب: '):
        logs.filter(pk=log.pk).update(operation='تعديل حساب')

    for log in logs.filter(operation__startswith='حذف حساب: '):
        logs.filter(pk=log.pk).update(operation='حذف حساب')

    for log in logs.filter(operation__startswith='فشل تسجيل دخول: '):
        logs.filter(pk=log.pk).update(operation='فشل تسجيل دخول')


def backwards(apps, schema_editor):
    if not _has_operationlog_table(schema_editor):
        return


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0016_repair_operationlog_history'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
