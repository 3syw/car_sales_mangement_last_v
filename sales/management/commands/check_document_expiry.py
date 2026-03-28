from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import Car, Notification


class Command(BaseCommand):
    help = 'فحص تواريخ انتهاء مستندات السيارات وإنشاء تنبيهات قبل 30 يومًا.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        warning_deadline = today + timedelta(days=30)

        total_created = 0
        cars = Car.objects.all().only('id', 'brand', 'model_name', 'vin', 'insurance_expiry', 'registration_expiry')

        for car in cars:
            if car.insurance_expiry and today <= car.insurance_expiry <= warning_deadline:
                days_left = (car.insurance_expiry - today).days
                message = (
                    f"تنبيه أرشيف: تأمين السيارة {car.brand} {car.model_name} "
                    f"({car.vin}) ينتهي خلال {days_left} يوم."
                )
                if not Notification.objects.filter(message=message, created_at__date=today).exists():
                    Notification.objects.create(message=message)
                    total_created += 1

            if car.registration_expiry and today <= car.registration_expiry <= warning_deadline:
                days_left = (car.registration_expiry - today).days
                message = (
                    f"تنبيه أرشيف: استمارة السيارة {car.brand} {car.model_name} "
                    f"({car.vin}) تنتهي خلال {days_left} يوم."
                )
                if not Notification.objects.filter(message=message, created_at__date=today).exists():
                    Notification.objects.create(message=message)
                    total_created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'تم فحص المستندات بنجاح. عدد التنبيهات الجديدة: {total_created}'
            )
        )
