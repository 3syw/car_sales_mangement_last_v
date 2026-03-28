from django.core.exceptions import ValidationError

from .models import DailyClosing, FiscalPeriodClosing
from .tenant_context import get_current_tenant_db_alias


def _resolve_tenant_alias(alias=''):
    candidate = (alias or get_current_tenant_db_alias() or '').strip()
    if candidate.startswith('tenant_'):
        return candidate
    return ''


def _normalize_operation_date(operation_date):
    if operation_date is None:
        return None
    if hasattr(operation_date, 'date'):
        return operation_date.date()
    return operation_date


def get_last_closed_date(alias=''):
    tenant_alias = _resolve_tenant_alias(alias)
    if not tenant_alias:
        return None

    try:
        return (
            DailyClosing.objects.using(tenant_alias)
            .order_by('-closing_date')
            .values_list('closing_date', flat=True)
            .first()
        )
    except Exception:
        return None


def get_locked_fiscal_period(operation_date, alias=''):
    tenant_alias = _resolve_tenant_alias(alias)
    normalized_date = _normalize_operation_date(operation_date)
    if not tenant_alias or normalized_date is None:
        return None

    try:
        return (
            FiscalPeriodClosing.objects.using(tenant_alias)
            .filter(
                is_locked=True,
                period_start__lte=normalized_date,
                period_end__gte=normalized_date,
            )
            .order_by('-period_end', '-created_at')
            .first()
        )
    except Exception:
        return None


def enforce_open_period_or_raise(operation_date, alias='', action_label='تعديل العملية'):
    tenant_alias = _resolve_tenant_alias(alias)
    normalized_date = _normalize_operation_date(operation_date)

    if not tenant_alias or normalized_date is None:
        return

    last_closed = get_last_closed_date(tenant_alias)
    if last_closed is None:
        return

    if normalized_date <= last_closed:
        operation_text = normalized_date.strftime('%Y-%m-%d')
        closed_text = last_closed.strftime('%Y-%m-%d')
        raise ValidationError(
            f'لا يمكن {action_label} بتاريخ {operation_text} لأن اليومية مغلقة حتى {closed_text}.'
        )

    locked_period = get_locked_fiscal_period(normalized_date, tenant_alias)
    if locked_period is not None:
        start_text = locked_period.period_start.strftime('%Y-%m-%d')
        end_text = locked_period.period_end.strftime('%Y-%m-%d')
        raise ValidationError(
            f'لا يمكن {action_label} بتاريخ {normalized_date:%Y-%m-%d} لأن الفترة المالية مغلقة ({start_text} -> {end_text}).'
        )
