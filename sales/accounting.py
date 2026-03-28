from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import Car, FinanceVoucher, FinancialAccount, FinancialContainer, JournalEntry, JournalEntryLine


def _manager(model_class, alias):
    if alias:
        return model_class.objects.using(alias)
    return model_class.objects


DEFAULT_ACCOUNT_DEFINITIONS = [
    {'code': '1000', 'name': 'الأصول', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': None},
    {'code': '1100', 'name': 'النقدية وما في حكمها', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': '1000'},
    {'code': '1110', 'name': 'الصندوق الرئيسي', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': '1100'},
    {'code': '1120', 'name': 'الحساب البنكي', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': '1100'},
    {'code': '1130', 'name': 'ذمم العملاء', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': '1000'},
    {'code': '1200', 'name': 'مخزون السيارات', 'account_type': FinancialAccount.ACCOUNT_TYPE_ASSET, 'parent_code': '1000'},
    {'code': '2000', 'name': 'الخصوم', 'account_type': FinancialAccount.ACCOUNT_TYPE_LIABILITY, 'parent_code': None},
    {'code': '2100', 'name': 'ذمم الموردين', 'account_type': FinancialAccount.ACCOUNT_TYPE_LIABILITY, 'parent_code': '2000'},
    {'code': '3000', 'name': 'حقوق الملكية', 'account_type': FinancialAccount.ACCOUNT_TYPE_EQUITY, 'parent_code': None},
    {'code': '4000', 'name': 'الإيرادات', 'account_type': FinancialAccount.ACCOUNT_TYPE_REVENUE, 'parent_code': None},
    {'code': '4100', 'name': 'إيرادات متنوعة', 'account_type': FinancialAccount.ACCOUNT_TYPE_REVENUE, 'parent_code': '4000'},
    {'code': '4200', 'name': 'إيرادات مبيعات السيارات', 'account_type': FinancialAccount.ACCOUNT_TYPE_REVENUE, 'parent_code': '4000'},
    {'code': '5000', 'name': 'المصروفات', 'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE, 'parent_code': None},
    {'code': '5100', 'name': 'مصروفات تشغيلية', 'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE, 'parent_code': '5000'},
    {'code': '5110', 'name': 'مصروفات صيانة سيارات مباعة', 'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE, 'parent_code': '5000'},
    {'code': '5115', 'name': 'تكلفة البضاعة المباعة', 'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE, 'parent_code': '5000'},
    {'code': '5200', 'name': 'مدفوعات متنوعة', 'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE, 'parent_code': '5000'},
]


ACCOUNT_CHOICE_TO_CODE = {
    FinanceVoucher.ACCOUNT_OPERATING_EXPENSES: '5100',
    FinanceVoucher.ACCOUNT_MAINTENANCE_SOLD_CARS: '5110',
    FinanceVoucher.ACCOUNT_CASH_BOX: '1110',
    FinanceVoucher.ACCOUNT_BANK: '1120',
}


def ensure_default_chart_of_accounts(alias=''):
    account_manager = _manager(FinancialAccount, alias)
    account_map = {}

    for definition in DEFAULT_ACCOUNT_DEFINITIONS:
        defaults = {
            'name': definition['name'],
            'account_type': definition['account_type'],
            'is_system': True,
            'is_active': True,
        }
        account, _created = account_manager.get_or_create(code=definition['code'], defaults=defaults)

        updates = {}
        if account.name != definition['name']:
            updates['name'] = definition['name']
        if account.account_type != definition['account_type']:
            updates['account_type'] = definition['account_type']
        if not account.is_system:
            updates['is_system'] = True
        if updates:
            for key, value in updates.items():
                setattr(account, key, value)
            if alias:
                account.save(using=alias, update_fields=list(updates.keys()))
            else:
                account.save(update_fields=list(updates.keys()))

        account_map[definition['code']] = account

    for definition in DEFAULT_ACCOUNT_DEFINITIONS:
        account = account_map[definition['code']]
        parent_code = definition['parent_code']
        parent = account_map.get(parent_code) if parent_code else None
        parent_id = parent.pk if parent else None
        if account.parent_id != parent_id:
            account.parent_id = parent_id
            if alias:
                account.save(using=alias, update_fields=['parent'])
            else:
                account.save(update_fields=['parent'])

    return account_map


def ensure_default_financial_containers(alias=''):
    account_map = ensure_default_chart_of_accounts(alias)
    container_manager = _manager(FinancialContainer, alias)

    defaults = [
        {
            'name': 'الخزينة الرئيسية',
            'container_type': FinancialContainer.TYPE_MAIN_CASH,
            'currency': 'SR',
            'linked_account': account_map['1110'],
        },
        {
            'name': 'الحساب البنكي الرئيسي',
            'container_type': FinancialContainer.TYPE_BANK,
            'currency': 'SR',
            'linked_account': account_map['1120'],
        },
    ]

    created_or_existing = []
    for container_def in defaults:
        container, _created = container_manager.get_or_create(
            name=container_def['name'],
            defaults={
                'container_type': container_def['container_type'],
                'currency': container_def['currency'],
                'linked_account': container_def['linked_account'],
                'opening_balance': Decimal('0'),
                'is_active': True,
            },
        )
        created_or_existing.append(container)

    return created_or_existing


def get_default_financial_container(alias='', preferred_type=FinancialContainer.TYPE_MAIN_CASH, currency='SR'):
    ensure_default_financial_containers(alias)
    container_manager = _manager(FinancialContainer, alias)

    container = container_manager.filter(
        is_active=True,
        container_type=preferred_type,
        currency=currency,
    ).order_by('id').first()
    if container is not None:
        return container

    container = container_manager.filter(is_active=True, container_type=preferred_type).order_by('id').first()
    if container is not None:
        return container

    return container_manager.filter(is_active=True).order_by('id').first()


def _next_journal_entry_number(alias, entry_date):
    prefix = f"JE-{entry_date.strftime('%Y%m%d')}-"
    last_entry = (
        _manager(JournalEntry, alias)
        .filter(entry_number__startswith=prefix)
        .order_by('-entry_number')
        .first()
    )
    next_sequence = 1
    if last_entry is not None:
        try:
            next_sequence = int(last_entry.entry_number.split('-')[-1]) + 1
        except Exception:
            next_sequence = 1

    return f"{prefix}{next_sequence:04d}"


def _resolve_liquidity_target(voucher, account_map, alias):
    container = None
    account = None

    if voucher.financial_container_id:
        container = _manager(FinancialContainer, alias).filter(pk=voucher.financial_container_id).first()

    preferred_type = FinancialContainer.TYPE_MAIN_CASH
    if container is not None:
        preferred_type = container.container_type
    elif voucher.debit_account == FinanceVoucher.ACCOUNT_BANK or voucher.credit_account == FinanceVoucher.ACCOUNT_BANK:
        preferred_type = FinancialContainer.TYPE_BANK

    if container is None:
        container = get_default_financial_container(alias, preferred_type=preferred_type, currency=voucher.currency)

    if container is not None and container.linked_account_id:
        account = _manager(FinancialAccount, alias).filter(pk=container.linked_account_id).first()

    if account is None:
        fallback_code = '1120' if preferred_type == FinancialContainer.TYPE_BANK else '1110'
        account = account_map.get(fallback_code)

    return account, container


def _resolve_voucher_accounts(voucher, account_map, alias):
    liquidity_account, liquidity_container = _resolve_liquidity_target(voucher, account_map, alias)

    if voucher.voucher_type == 'receipt':
        return liquidity_account, account_map.get('4100'), liquidity_account, liquidity_container

    if voucher.voucher_type == 'payment':
        return account_map.get('5200'), liquidity_account, liquidity_account, liquidity_container

    if voucher.voucher_type == 'operating':
        return account_map.get('5100'), liquidity_account, liquidity_account, liquidity_container

    if voucher.voucher_type == 'settlement':
        return liquidity_account, account_map.get('1130'), liquidity_account, liquidity_container

    if voucher.voucher_type == 'maintenance':
        mapped_debit = ACCOUNT_CHOICE_TO_CODE.get(voucher.debit_account, '5110')
        mapped_credit = ACCOUNT_CHOICE_TO_CODE.get(voucher.credit_account)
        debit_account = account_map.get(mapped_debit) or account_map.get('5110')
        credit_account = account_map.get(mapped_credit) if mapped_credit else liquidity_account
        return debit_account, credit_account, liquidity_account, liquidity_container

    return liquidity_account, account_map.get('4100'), liquidity_account, liquidity_container


def _resolve_cost_center_car(voucher, alias):
    if voucher.linked_car_id:
        return _manager(Car, alias).filter(pk=voucher.linked_car_id).first()

    maintenance_record = getattr(voucher, 'maintenance_record', None)
    if maintenance_record is not None and maintenance_record.car_id:
        return _manager(Car, alias).filter(pk=maintenance_record.car_id).first()

    return None


def sync_journal_entry_for_voucher(voucher, alias='', created_by_id=None):
    used_alias = alias or getattr(voucher._state, 'db', '')
    if not used_alias:
        return None

    amount_value = Decimal(voucher.amount or Decimal('0'))
    if amount_value <= Decimal('0'):
        return None

    account_map = ensure_default_chart_of_accounts(used_alias)
    ensure_default_financial_containers(used_alias)

    debit_account, credit_account, liquidity_account, liquidity_container = _resolve_voucher_accounts(
        voucher,
        account_map,
        used_alias,
    )

    if debit_account is None or credit_account is None:
        return None

    entry_manager = _manager(JournalEntry, used_alias)
    line_manager = _manager(JournalEntryLine, used_alias)

    with transaction.atomic(using=used_alias):
        entry = entry_manager.filter(source_model='FinanceVoucher', source_pk=str(voucher.pk)).first()
        entry_description = f"{voucher.get_voucher_type_display()} #{voucher.voucher_number}"

        if entry is None:
            entry = entry_manager.create(
                entry_number=_next_journal_entry_number(used_alias, voucher.voucher_date),
                entry_date=voucher.voucher_date,
                description=entry_description,
                source_model='FinanceVoucher',
                source_pk=str(voucher.pk),
                source_reference=voucher.voucher_number,
                created_by_id=created_by_id,
            )
        else:
            entry.entry_date = voucher.voucher_date
            entry.description = entry_description
            entry.source_reference = voucher.voucher_number
            if created_by_id and not entry.created_by_id:
                entry.created_by_id = created_by_id
            entry.save(using=used_alias, update_fields=['entry_date', 'description', 'source_reference', 'created_by'])
            line_manager.filter(entry_id=entry.pk).delete()

        linked_car = _resolve_cost_center_car(voucher, used_alias)

        debit_container = liquidity_container if (liquidity_account and debit_account.pk == liquidity_account.pk) else None
        credit_container = liquidity_container if (liquidity_account and credit_account.pk == liquidity_account.pk) else None

        line_manager.create(
            entry=entry,
            account=debit_account,
            line_description=voucher.reason or entry_description,
            debit=amount_value,
            credit=Decimal('0'),
            currency=voucher.currency,
            container=debit_container,
            car=linked_car,
        )
        line_manager.create(
            entry=entry,
            account=credit_account,
            line_description=voucher.reason or entry_description,
            debit=Decimal('0'),
            credit=amount_value,
            currency=voucher.currency,
            container=credit_container,
            car=linked_car,
        )

    return entry


def delete_journal_entry_for_voucher(voucher_id, alias=''):
    used_alias = alias or ''
    if not used_alias:
        return

    _manager(JournalEntry, used_alias).filter(source_model='FinanceVoucher', source_pk=str(voucher_id)).delete()


def build_trial_balance_rows(alias='', as_of_date=None):
    used_date = as_of_date or date.today()
    line_rows = (
        _manager(JournalEntryLine, alias)
        .filter(entry__entry_date__lte=used_date)
        .values('account_id', 'account__code', 'account__name', 'account__account_type')
        .annotate(total_debit=Sum('debit'), total_credit=Sum('credit'))
        .order_by('account__code')
    )

    rows = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')

    for item in line_rows:
        debit_value = item['total_debit'] or Decimal('0')
        credit_value = item['total_credit'] or Decimal('0')
        balance_value = debit_value - credit_value
        balance_side = 'مدين' if balance_value >= Decimal('0') else 'دائن'

        rows.append({
            'account_code': item['account__code'],
            'account_name': item['account__name'],
            'account_type': item['account__account_type'],
            'debit': debit_value,
            'credit': credit_value,
            'balance': balance_value,
            'balance_side': balance_side,
        })

        total_debit += debit_value
        total_credit += credit_value

    return {
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'difference': total_debit - total_credit,
    }
