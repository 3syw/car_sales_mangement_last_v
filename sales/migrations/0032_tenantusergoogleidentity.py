from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0031_debtpayment_deleted_at_debtpayment_deleted_by_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantUserGoogleIdentity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('google_sub', models.CharField(max_length=255, unique=True, verbose_name='Google Subject ID')),
                ('google_email', models.EmailField(max_length=254, verbose_name='Google Email')),
                ('email_verified', models.BooleanField(default=False, verbose_name='البريد موثق من Google')),
                ('last_verified_at', models.DateTimeField(auto_now=True, verbose_name='آخر تحقق')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('user', models.OneToOneField(on_delete=models.deletion.CASCADE, related_name='google_identity', to='auth.user', verbose_name='الحساب')),
            ],
            options={
                'verbose_name': 'ربط حساب Google',
                'verbose_name_plural': 'روابط حسابات Google',
            },
        ),
    ]
