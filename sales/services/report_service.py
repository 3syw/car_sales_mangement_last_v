from decimal import Decimal
from datetime import timedelta

from django.utils import timezone

from sales.models import Car, InventoryTransaction, Sale


class ReportService:
    @staticmethod
    def car_profit_rows(*, tenant_alias):
        rows = []
        sales = Sale.objects.using(tenant_alias).select_related('car').all()
        for sale in sales:
            car = sale.car
            total_cost = car.total_cost_price or Decimal('0')
            rows.append({
                'car_id': car.id,
                'vin': car.vin,
                'purchase_cost': car.cost_price or Decimal('0'),
                'total_cost': total_cost,
                'sale_price': sale.sale_price or Decimal('0'),
                'actual_profit': (sale.sale_price or Decimal('0')) - total_cost,
            })
        return rows

    @staticmethod
    def showroom_performance(*, tenant_alias):
        today = timezone.localdate()
        sold_qs = Sale.objects.using(tenant_alias).select_related('car').all()
        sold_count = sold_qs.count()

        total_sales = sum((sale.sale_price or Decimal('0') for sale in sold_qs), Decimal('0'))
        total_profit = sum((sale.actual_profit for sale in sold_qs), Decimal('0'))
        avg_profit = (total_profit / sold_count) if sold_count else Decimal('0')

        durations = []
        for sale in sold_qs:
            if sale.car and sale.car.created_at and sale.sale_date:
                durations.append((sale.sale_date.date() - sale.car.created_at.date()).days)
        avg_days_in_stock = (sum(durations) / len(durations)) if durations else 0

        return {
            'total_sales': total_sales,
            'sold_count': sold_count,
            'average_profit_per_car': avg_profit,
            'average_days_in_inventory': avg_days_in_stock,
            'as_of_date': today,
        }

    @staticmethod
    def inventory_turnover(*, tenant_alias):
        sold_count = Sale.objects.using(tenant_alias).count()
        available_count = Car.objects.using(tenant_alias).filter(is_sold=False).count()
        denominator = available_count if available_count > 0 else 1
        return Decimal(sold_count) / Decimal(denominator)

    @staticmethod
    def stale_cars(*, tenant_alias, days_threshold):
        cutoff = timezone.now() - timedelta(days=int(days_threshold))
        return Car.objects.using(tenant_alias).filter(is_sold=False, created_at__lte=cutoff).order_by('created_at')

    @staticmethod
    def inventory_movements(*, tenant_alias):
        return InventoryTransaction.objects.using(tenant_alias).select_related('car').order_by('-transaction_date', '-id')
