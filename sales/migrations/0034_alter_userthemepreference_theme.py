from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0033_userthemepreference'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userthemepreference',
            name='theme',
            field=models.CharField(
                choices=[('dark', 'مظلم'), ('light', 'مشمس'), ('auto', 'تلقائي')],
                default='dark',
                max_length=10,
                verbose_name='الثيم',
            ),
        ),
    ]
