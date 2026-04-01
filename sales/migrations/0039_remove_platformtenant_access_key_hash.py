from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0038_seed_default_currencies'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='platformtenant',
            name='access_key_hash',
        ),
    ]
