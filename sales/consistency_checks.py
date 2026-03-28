from django.db.models import F, Sum
from django.utils import timezone

from .models import Car, CarMaintenance, DebtPayment, FinanceVoucher, Sale
from .tenant_context import get_current_tenant_db_alias


def _resolve_tenant_alias(alias=''):
    candidate = (alias or get_current_tenant_db_alias() or '').strip()
    if candidate.startswith('tenant_'):
        return candidate
    return ''


def _manager(model, alias=''):
    if alias:
        return model.objects.using(alias)
    return model.objects


def _build_text_samples(objects, formatter, limit=6):
    samples = []
    for obj in objects[:limit]:
        try:
            samples.append(formatter(obj))
        except Exception:
            samples.append(str(obj))
    return samples


def build_financial_consistency_report(alias=''):
    tenant_alias = _resolve_tenant_alias(alias)

    sold_without_sale_qs = _manager(Car, tenant_alias).filter(is_sold=True, sale__isnull=True).order_by('-created_at')
    unsold_with_sale_qs = _manager(Car, tenant_alias).filter(is_sold=False, sale__isnull=False).order_by('-created_at')
    sale_overpaid_qs = _manager(Sale, tenant_alias).select_related('car', 'customer').filter(amount_paid__gt=F('sale_price')).order_by('-sale_date')
    maintenance_without_voucher_qs = _manager(CarMaintenance, tenant_alias).select_related('car').filter(journal_voucher__isnull=True).order_by('-operation_date')
    orphan_maintenance_voucher_qs = _manager(FinanceVoucher, tenant_alias).filter(voucher_type='maintenance', maintenance_record__isnull=True).order_by('-voucher_date')

    receipt_numbers = set(_manager(DebtPayment, tenant_alias).values_list('receipt_number', flat=True))
    voucher_numbers = set(_manager(FinanceVoucher, tenant_alias).values_list('voucher_number', flat=True))

    debts_without_voucher_qs = (
        _manager(DebtPayment, tenant_alias)
        .select_related('sale__car', 'sale__customer')
        .exclude(receipt_number__in=voucher_numbers)
        .order_by('-payment_date')
    )
    settlement_without_debt_qs = (
        _manager(FinanceVoucher, tenant_alias)
        .filter(voucher_type='settlement')
        .exclude(voucher_number__in=receipt_numbers)
        .order_by('-voucher_date')
    )

    payment_totals = _manager(DebtPayment, tenant_alias).values('sale_id').annotate(total_paid=Sum('paid_amount'))
    sale_ids = [row['sale_id'] for row in payment_totals if row.get('sale_id')]
    sales_map = _manager(Sale, tenant_alias).select_related('car', 'customer').in_bulk(sale_ids)

    over_collected_rows = []
    for row in payment_totals:
        sale_id = row.get('sale_id')
        if not sale_id:
            continue

        sale = sales_map.get(sale_id)
        total_paid = row.get('total_paid')
        if sale is None or total_paid is None:
            continue

        if total_paid > sale.sale_price:
            over_collected_rows.append({
                'sale': sale,
                'total_paid': total_paid,
                'over_amount': total_paid - sale.sale_price,
            })

    issues = [
        {
            'key': 'sold_without_sale',
            'title': 'سيارات حالتها مباعة دون سجل بيع',
            'severity': 'high',
            'count': sold_without_sale_qs.count(),
            'samples': _build_text_samples(
                list(sold_without_sale_qs[:12]),
                lambda car: f"{car.brand} {car.model_name} ({car.vin})",
            ),
        },
        {
            'key': 'unsold_with_sale',
            'title': 'سيارات غير مباعة لكنها مرتبطة بسجل بيع',
            'severity': 'high',
            'count': unsold_with_sale_qs.count(),
            'samples': _build_text_samples(
                list(unsold_with_sale_qs[:12]),
                lambda car: f"{car.brand} {car.model_name} ({car.vin})",
            ),
        },
        {
            'key': 'sale_overpaid',
            'title': 'مبيعات المبلغ المدفوع فيها أكبر من سعر البيع',
            'severity': 'high',
            'count': sale_overpaid_qs.count(),
            'samples': _build_text_samples(
                list(sale_overpaid_qs[:12]),
                lambda sale: f"بيع #{sale.id} - {sale.customer.name} - {sale.amount_paid} > {sale.sale_price}",
            ),
        },
        {
            'key': 'debt_without_voucher',
            'title': 'دفعات ديون بلا سند تسديد مقابل',
            'severity': 'medium',
            'count': debts_without_voucher_qs.count(),
            'samples': _build_text_samples(
                list(debts_without_voucher_qs[:12]),
                lambda payment: f"{payment.receipt_number} - {payment.sale.customer.name} - {payment.paid_amount}",
            ),
        },
        {
            'key': 'settlement_without_debt',
            'title': 'سندات تسديد بدون دفعة دين مقابلة',
            'severity': 'medium',
            'count': settlement_without_debt_qs.count(),
            'samples': _build_text_samples(
                list(settlement_without_debt_qs[:12]),
                lambda voucher: f"{voucher.voucher_number} - {voucher.amount} {voucher.currency}",
            ),
        },
        {
            'key': 'maintenance_without_voucher',
            'title': 'مصروفات صيانة غير مربوطة بقيد محاسبي',
            'severity': 'medium',
            'count': maintenance_without_voucher_qs.count(),
            'samples': _build_text_samples(
                list(maintenance_without_voucher_qs[:12]),
                lambda row: f"صيانة {row.car.brand} ({row.car.vin}) بتاريخ {row.operation_date}",
            ),
        },
        {
            'key': 'orphan_maintenance_voucher',
            'title': 'قيود صيانة بلا سجل صيانة مرتبط',
            'severity': 'medium',
            'count': orphan_maintenance_voucher_qs.count(),
            'samples': _build_text_samples(
                list(orphan_maintenance_voucher_qs[:12]),
                lambda voucher: f"{voucher.voucher_number} - {voucher.amount} {voucher.currency}",
            ),
        },
        {
            'key': 'over_collected_debt',
            'title': 'تحصيلات ديون تتجاوز سعر البيع',
            'severity': 'high',
            'count': len(over_collected_rows),
            'samples': _build_text_samples(
                over_collected_rows[:12],
                lambda row: (
                    f"بيع #{row['sale'].id} - {row['sale'].customer.name} - "
                    f"تجاوز {row['over_amount']}"
                ),
            ),
        },
    ]

    total_issues = sum(item['count'] for item in issues)
    is_clean = total_issues == 0

    return {
        'generated_at': timezone.now(),
        'tenant_alias': tenant_alias,
        'is_clean': is_clean,
        'total_issues': total_issues,
        'issues': issues,
    }
