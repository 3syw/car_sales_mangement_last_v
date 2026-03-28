from decimal import Decimal
from io import StringIO
from datetime import timedelta

from celery import shared_task
from celery.result import AsyncResult
from django.core.management import call_command
from django.utils import timezone

from .models import Car, Sale
from .tenant_context import clear_current_tenant, set_current_tenant
from .tenant_database import ensure_tenant_connection, normalize_tenant_id


def _inventory_turnover(alias):
    sold_count = Sale.objects.using(alias).count()
    available_count = Car.objects.using(alias).filter(is_sold=False).count()
    denominator = available_count if available_count > 0 else 1
    return Decimal(sold_count) / Decimal(denominator)


def _stale_cars_count(alias, days_threshold):
    cutoff = timezone.now() - timedelta(days=int(days_threshold))
    return Car.objects.using(alias).filter(is_sold=False, created_at__lte=cutoff).count()


def _showroom_performance(alias):
    today = timezone.localdate()
    sold_sales = list(Sale.objects.using(alias).select_related('car').all())
    sold_count = len(sold_sales)

    total_sales = sum((sale.sale_price or Decimal('0') for sale in sold_sales), Decimal('0'))
    total_profit = sum((sale.actual_profit for sale in sold_sales), Decimal('0'))
    avg_profit = (total_profit / sold_count) if sold_count else Decimal('0')

    durations = []
    for sale in sold_sales:
        if sale.car and sale.car.created_at and sale.sale_date:
            durations.append((sale.sale_date.date() - sale.car.created_at.date()).days)
    avg_days_in_stock = (sum(durations) / len(durations)) if durations else 0

    return {
        'total_sales': total_sales,
        'sold_count': sold_count,
        'average_profit_per_car': avg_profit,
        'average_days_in_inventory': avg_days_in_stock,
        'as_of_date': today.isoformat(),
    }


def _capture_command(command_name, **kwargs):
    stdout = StringIO()
    stderr = StringIO()
    call_command(command_name, stdout=stdout, stderr=stderr, **kwargs)
    return {
        'command': command_name,
        'stdout': stdout.getvalue(),
        'stderr': stderr.getvalue(),
    }


@shared_task(bind=True, name='sales.tasks.run_financial_consistency_report')
def run_financial_consistency_report_task(self, tenant_id='', report_path=''):
    normalized_tenant = normalize_tenant_id(tenant_id or '')
    kwargs = {
        'report_path': report_path or '',
    }
    if normalized_tenant:
        kwargs['tenant_id'] = normalized_tenant

    output = _capture_command('check_financial_consistency', **kwargs)
    return {
        'status': 'success',
        'task_id': self.request.id,
        'tenant_id': normalized_tenant,
        **output,
    }


@shared_task(bind=True, name='sales.tasks.run_tenant_backup')
def run_tenant_backup_task(self, tenant_id, actor='system'):
    normalized_tenant = normalize_tenant_id(tenant_id or '')
    if not normalized_tenant:
        raise ValueError('tenant_id is required for tenant backup task.')

    output = _capture_command('backup_tenant', tenant_id=normalized_tenant, actor=(actor or 'system'))
    return {
        'status': 'success',
        'task_id': self.request.id,
        'tenant_id': normalized_tenant,
        **output,
    }


@shared_task(bind=True, name='sales.tasks.run_db_isolation_audit')
def run_db_isolation_audit_task(self, cleanup=False, force=False, skip_backup=False, report_path=''):
    kwargs = {
        'cleanup': bool(cleanup),
        'force': bool(force),
        'skip_backup': bool(skip_backup),
        'report_path': report_path or '',
    }
    output = _capture_command('enforce_db_isolation', **kwargs)
    return {
        'status': 'success',
        'task_id': self.request.id,
        **output,
    }


@shared_task(bind=True, name='sales.tasks.build_tenant_reports_snapshot')
def build_tenant_reports_snapshot_task(self, tenant_id):
    normalized_tenant = normalize_tenant_id(tenant_id or '')
    if not normalized_tenant:
        raise ValueError('tenant_id is required to build reports snapshot.')

    alias = ensure_tenant_connection(normalized_tenant)
    if not alias:
        raise ValueError(f'Unable to resolve tenant alias for {normalized_tenant}.')

    set_current_tenant(normalized_tenant, alias)
    try:
        sales = list(Sale.objects.using(alias).select_related('car').all())
        total_sales_by_currency = {}
        total_profit_by_currency = {}
        outstanding_by_currency = {}

        for sale in sales:
            currency = getattr(sale.car, 'currency', 'SR')
            total_sales_by_currency[currency] = total_sales_by_currency.get(currency, Decimal('0')) + (sale.sale_price or Decimal('0'))
            total_profit_by_currency[currency] = total_profit_by_currency.get(currency, Decimal('0')) + (sale.actual_profit or Decimal('0'))
            outstanding_by_currency[currency] = outstanding_by_currency.get(currency, Decimal('0')) + (sale.remaining_amount or Decimal('0'))

        snapshot = {
            'status': 'success',
            'task_id': self.request.id,
            'tenant_id': normalized_tenant,
            'sold_count': len(sales),
            'available_count': Car.objects.using(alias).filter(is_sold=False).count(),
            'inventory_turnover': str(_inventory_turnover(alias)),
            'performance': _showroom_performance(alias),
            'stale_cars': {
                '30_plus': _stale_cars_count(alias, 30),
                '60_plus': _stale_cars_count(alias, 60),
                '90_plus': _stale_cars_count(alias, 90),
            },
            'totals': {
                'sales_by_currency': {key: str(value) for key, value in total_sales_by_currency.items()},
                'profit_by_currency': {key: str(value) for key, value in total_profit_by_currency.items()},
                'outstanding_by_currency': {key: str(value) for key, value in outstanding_by_currency.items()},
            },
        }
        return snapshot
    finally:
        clear_current_tenant()


@shared_task(bind=True, name='sales.tasks.check_task_status')
def check_task_status_task(self, task_id):
    info = AsyncResult(task_id)
    payload = {
        'task_id': task_id,
        'status': info.status,
        'ready': info.ready(),
        'successful': info.successful() if info.ready() else False,
    }
    if info.ready():
        payload['result'] = info.result
    return payload
