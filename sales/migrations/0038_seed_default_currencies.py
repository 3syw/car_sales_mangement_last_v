from django.db import migrations


def seed_default_currencies(apps, schema_editor):
    Currency = apps.get_model('sales', 'Currency')
    table_names = schema_editor.connection.introspection.table_names()
    if 'sales_currency' not in table_names:
        return

    default_currencies = [
        {'code': 'SR', 'name': 'ريال سعودي', 'symbol': 'SR'},
        {'code': '$', 'name': 'دولار أمريكي', 'symbol': '$'},
        {'code': '£', 'name': 'جنيه إسترليني', 'symbol': '£'},
        {'code': 'YER', 'name': 'ريال يمني', 'symbol': 'YER'},
        {'code': 'KRW', 'name': 'وون كوري', 'symbol': 'KRW'},
        {'code': 'CNY', 'name': 'يوان صيني', 'symbol': 'CNY'},
        {'code': 'EUR', 'name': 'يورو', 'symbol': 'EUR'},
    ]

    for item in default_currencies:
        Currency.objects.update_or_create(
            code=item['code'],
            defaults={
                'name': item['name'],
                'symbol': item['symbol'],
                'is_active': True,
            },
        )


def noop_reverse(apps, schema_editor):
    # Keep seeded currencies to avoid removing data used by transactions/rates.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0037_alter_car_currency_alter_financevoucher_currency_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_default_currencies, noop_reverse),
    ]
