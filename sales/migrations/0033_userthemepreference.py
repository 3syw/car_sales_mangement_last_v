from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0032_tenantusergoogleidentity'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserThemePreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant_id', models.SlugField(blank=True, default='', max_length=50, verbose_name='معرف المعرض')),
                ('username', models.CharField(max_length=150, verbose_name='اسم المستخدم')),
                ('theme', models.CharField(choices=[('dark', 'مظلم'), ('light', 'مشمس')], default='dark', max_length=10, verbose_name='الثيم')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')),
            ],
            options={
                'verbose_name': 'تفضيل ثيم المستخدم',
                'verbose_name_plural': 'تفضيلات ثيم المستخدمين',
            },
        ),
        migrations.AddConstraint(
            model_name='userthemepreference',
            constraint=models.UniqueConstraint(fields=('tenant_id', 'username'), name='uniq_theme_pref_tenant_username'),
        ),
    ]
