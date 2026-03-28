from decimal import Decimal

from django.db.models import Sum

from sales.models import CustomerAccount, DebtPayment, Sale


class DebtService:
    @staticmethod
    def get_customer_account_snapshot(*, tenant_alias, customer_id):
        return CustomerAccount.objects.using(tenant_alias).filter(customer_id=customer_id).first()

    @staticmethod
    def get_total_outstanding(*, tenant_alias):
        totals = Sale.objects.using(tenant_alias).aggregate(
            total_debt=Sum('sale_price'),
            total_paid=Sum('amount_paid'),
        )
        total_debt = totals['total_debt'] or Decimal('0')
        total_paid = totals['total_paid'] or Decimal('0')
        return total_debt - total_paid

    @staticmethod
    def get_collected_payments_total(*, tenant_alias):
        total = DebtPayment.objects.using(tenant_alias).aggregate(total=Sum('paid_amount'))['total']
        return total or Decimal('0')
