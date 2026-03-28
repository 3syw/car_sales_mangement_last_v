import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.accounting import ensure_default_chart_of_accounts, ensure_default_financial_containers, get_default_financial_container
from sales.models import (
    AuditLog,
    Car,
    Customer,
    FinanceVoucher,
    FinancialAccount,
    FinancialContainer,
    JournalEntry,
    JournalEntryLine,
    OperationLog,
    Sale,
    SaleInstallment,
)


SALE_DOWN_PAYMENT_MARKER = '[SALE_DOWN_PAYMENT]'


def _as_decimal(value, default='0'):
    if value is None or value == '':
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValidationError('قيمة رقمية غير صالحة.') from exc


def _next_receipt_number(alias):
    today = timezone.localdate().strftime('%Y%m%d')
    prefix = f"QBD-{today}-"
    last_voucher = (
        FinanceVoucher.objects.using(alias)
        .filter(voucher_type='receipt', voucher_number__startswith=prefix)
        .order_by('-voucher_number')
        .first()
    )
    next_sequence = 1
    if last_voucher is not None:
        try:
            next_sequence = int(last_voucher.voucher_number.split('-')[-1]) + 1
        except Exception:
            next_sequence = 1
    return f"{prefix}{next_sequence:04d}"


def _next_journal_entry_number(alias, entry_date):
    prefix = f"JE-{entry_date.strftime('%Y%m%d')}-"
    last_entry = (
        JournalEntry.objects.using(alias)
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


def _normalize_schedule(payment_schedule):
    if payment_schedule is None or payment_schedule == '':
        return []

    raw_items = payment_schedule
    if isinstance(payment_schedule, str):
        text = payment_schedule.strip()
        if not text:
            return []
        try:
            raw_items = json.loads(text)
        except Exception as exc:
            raise ValidationError({'payment_schedule': 'تنسيق جدول الأقساط غير صالح.'}) from exc

    if not isinstance(raw_items, list):
        raise ValidationError({'payment_schedule': 'جدول الأقساط يجب أن يكون قائمة.'})

    normalized = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValidationError({'payment_schedule': f'القسط رقم {index} يجب أن يكون كائنًا.'})

        due_date_value = item.get('due_date')
        amount_value = item.get('amount')

        if not due_date_value:
            raise ValidationError({'payment_schedule': f'تاريخ استحقاق القسط رقم {index} مطلوب.'})

        try:
            due_date = datetime.strptime(str(due_date_value), '%Y-%m-%d').date()
        except Exception as exc:
            raise ValidationError({'payment_schedule': f'تاريخ القسط رقم {index} غير صالح (الصيغة YYYY-MM-DD).'}) from exc

        amount = _as_decimal(amount_value)
        if amount <= Decimal('0'):
            raise ValidationError({'payment_schedule': f'قيمة القسط رقم {index} يجب أن تكون أكبر من صفر.'})

        note = str(item.get('note') or '').strip()
        normalized.append({'due_date': due_date, 'amount': amount, 'note': note})

    normalized.sort(key=lambda row: row['due_date'])
    return normalized


@dataclass
class CreditSaleResult:
    sale: Sale
    receipt_voucher: FinanceVoucher | None
    journal_entry: JournalEntry


class SalesService:
    @staticmethod
    def execute_credit_sale(
        *,
        tenant_alias,
        car_id,
        customer_name,
        customer_phone,
        customer_national_id,
        total_sale_price,
        down_payment,
        payment_schedule=None,
        debt_due_date=None,
        sale_contract_image=None,
        actor=None,
        currency_rate=None,
        financial_container_id=None,
        request_path='',
        ip_address='',
        device_type='',
        browser='',
        geo_location='',
    ):
        used_alias = (tenant_alias or '').strip()
        if not used_alias.startswith('tenant_'):
            raise ValidationError('لا توجد بيئة معرض مفعلة لتنفيذ عملية البيع.')

        sale_price = _as_decimal(total_sale_price)
        amount_paid = _as_decimal(down_payment)
        fx_rate = _as_decimal(currency_rate, default='1') if currency_rate not in (None, '') else Decimal('1')

        if sale_price <= Decimal('0'):
            raise ValidationError({'sale_price': 'سعر البيع يجب أن يكون أكبر من صفر.'})

        if amount_paid < Decimal('0'):
            raise ValidationError({'amount_paid': 'الدفعة المقدمة لا يمكن أن تكون سالبة.'})

        if amount_paid > sale_price:
            raise ValidationError({'amount_paid': 'الدفعة المقدمة لا يمكن أن تتجاوز سعر البيع.'})

        if fx_rate <= Decimal('0'):
            raise ValidationError({'currency_rate': 'سعر الصرف يجب أن يكون أكبر من صفر.'})

        remaining_balance = sale_price - amount_paid

        if remaining_balance > Decimal('0') and not sale_contract_image:
            raise ValidationError({'sale_contract_image': 'يجب رفع عقد البيع الموقّع لإتمام البيع الآجل.'})

        schedule_rows = _normalize_schedule(payment_schedule)

        if remaining_balance > Decimal('0'):
            if schedule_rows:
                schedule_total = sum((row['amount'] for row in schedule_rows), Decimal('0'))
                if schedule_total != remaining_balance:
                    raise ValidationError({'payment_schedule': 'إجمالي الأقساط يجب أن يساوي المبلغ المتبقي.'})
            else:
                if debt_due_date is None:
                    debt_due_date = timezone.localdate() + timedelta(days=30)
                schedule_rows = [
                    {
                        'due_date': debt_due_date,
                        'amount': remaining_balance,
                        'note': 'قسط تلقائي (لم يتم إدخال جدول أقساط مفصل).',
                    }
                ]
        else:
            schedule_rows = []
            debt_due_date = None

        if schedule_rows:
            debt_due_date = schedule_rows[0]['due_date']

        ensure_default_chart_of_accounts(alias=used_alias)
        ensure_default_financial_containers(alias=used_alias)

        actor_id = None
        if actor is not None:
            user_model = get_user_model()
            if user_model.objects.using(used_alias).filter(pk=actor.pk).exists():
                actor_id = actor.pk

        with transaction.atomic(using=used_alias):
            car = (
                Car.objects.using(used_alias)
                .select_for_update()
                .filter(pk=car_id)
                .first()
            )
            if car is None:
                raise ValidationError({'car_id': 'السيارة غير موجودة.'})

            if car.is_sold:
                raise ValidationError({'car_id': 'لا يمكن إتمام العملية لأن السيارة مباعة مسبقاً.'})

            car.is_sold = True
            car.save(using=used_alias, update_fields=['is_sold'])

            customer, created = Customer.objects.using(used_alias).get_or_create(
                national_id=customer_national_id,
                defaults={
                    'name': customer_name,
                    'phone': customer_phone,
                },
            )

            if not created:
                changed = False
                if customer.name != customer_name:
                    customer.name = customer_name
                    changed = True
                if customer.phone != customer_phone:
                    customer.phone = customer_phone
                    changed = True
                if changed:
                    customer.save(using=used_alias, update_fields=['name', 'phone'])

            sale = Sale.objects.using(used_alias).create(
                car=car,
                customer=customer,
                sale_price=sale_price,
                amount_paid=amount_paid,
                debt_due_date=debt_due_date,
                sale_contract_image=sale_contract_image,
            )

            installment_objects = []
            for index, row in enumerate(schedule_rows, start=1):
                installment_objects.append(
                    SaleInstallment(
                        sale=sale,
                        installment_order=index,
                        due_date=row['due_date'],
                        amount=row['amount'],
                        note=row['note'],
                    )
                )

            if installment_objects:
                SaleInstallment.objects.using(used_alias).bulk_create(installment_objects)

            receipt_voucher = None
            liquidity_container = None
            liquidity_account = None
            debit_choice = FinanceVoucher.ACCOUNT_CASH_BOX

            if amount_paid > Decimal('0'):
                if financial_container_id:
                    liquidity_container = FinancialContainer.objects.using(used_alias).filter(pk=financial_container_id, is_active=True).first()
                    if liquidity_container is None:
                        raise ValidationError({'financial_container': 'الوعاء المالي المحدد غير صالح أو غير نشط.'})

                if liquidity_container is None:
                    liquidity_container = get_default_financial_container(
                        alias=used_alias,
                        preferred_type=FinancialContainer.TYPE_MAIN_CASH,
                        currency=car.currency,
                    )

                if liquidity_container and liquidity_container.currency != car.currency:
                    raise ValidationError({'financial_container': 'عملة الوعاء المالي يجب أن تطابق عملة السيارة.'})

                if liquidity_container and liquidity_container.container_type == FinancialContainer.TYPE_BANK:
                    debit_choice = FinanceVoucher.ACCOUNT_BANK

                receipt_voucher = FinanceVoucher.objects.using(used_alias).create(
                    voucher_type='receipt',
                    voucher_number=_next_receipt_number(used_alias),
                    voucher_date=timezone.localdate(),
                    person_name=customer.name,
                    amount=amount_paid,
                    currency=car.currency,
                    reason=(
                        f"{SALE_DOWN_PAYMENT_MARKER} "
                        f"دفعة مقدمة لبيع السيارة {car.brand} {car.model_name} ({car.vin})"
                    ),
                    linked_car=car,
                    financial_container=liquidity_container,
                    debit_account=debit_choice,
                    credit_account=FinanceVoucher.ACCOUNT_NONE,
                )

                # Keep this voucher as an operational document only to avoid
                # duplicating journal impact with the dedicated sale entry below.
                JournalEntry.objects.using(used_alias).filter(
                    source_model='FinanceVoucher',
                    source_pk=str(receipt_voucher.pk),
                ).delete()

            account_manager = FinancialAccount.objects.using(used_alias)
            account_receivable = account_manager.filter(code='1130').first()
            account_revenue = account_manager.filter(code='4200').first()
            account_inventory = account_manager.filter(code='1200').first()
            account_cogs, _created = account_manager.get_or_create(
                code='5115',
                defaults={
                    'name': 'تكلفة البضاعة المباعة',
                    'account_type': FinancialAccount.ACCOUNT_TYPE_EXPENSE,
                    'is_system': True,
                    'is_active': True,
                },
            )

            if liquidity_container and liquidity_container.linked_account_id:
                liquidity_account = account_manager.filter(pk=liquidity_container.linked_account_id).first()

            if liquidity_account is None:
                liquidity_account = account_manager.filter(code='1110').first()

            missing_accounts = []
            if account_receivable is None:
                missing_accounts.append('1130')
            if account_revenue is None:
                missing_accounts.append('4200')
            if account_inventory is None:
                missing_accounts.append('1200')
            if liquidity_account is None and amount_paid > Decimal('0'):
                missing_accounts.append('1110/1120')

            if missing_accounts:
                raise ValidationError(f"تعذر إنشاء القيد المحاسبي. الحسابات التالية غير متاحة: {', '.join(missing_accounts)}")

            sale_day = timezone.localdate()
            journal_entry = JournalEntry.objects.using(used_alias).create(
                entry_number=_next_journal_entry_number(used_alias, sale_day),
                entry_date=sale_day,
                description=f"قيد بيع آجل سيارة {car.brand} {car.model_name} ({car.vin})",
                source_model='Sale',
                source_pk=str(sale.pk),
                source_reference=f"SALE-{sale.pk}",
                created_by_id=actor_id,
            )

            if amount_paid > Decimal('0'):
                JournalEntryLine.objects.using(used_alias).create(
                    entry=journal_entry,
                    account=liquidity_account,
                    line_description=f"دفعة مقدمة - سيارة {car.vin}",
                    debit=amount_paid,
                    credit=Decimal('0'),
                    currency=car.currency,
                    container=liquidity_container,
                    car=car,
                )

            if remaining_balance > Decimal('0'):
                JournalEntryLine.objects.using(used_alias).create(
                    entry=journal_entry,
                    account=account_receivable,
                    line_description=f"ذمم العميل {customer.name} - سيارة {car.vin}",
                    debit=remaining_balance,
                    credit=Decimal('0'),
                    currency=car.currency,
                    car=car,
                )

            JournalEntryLine.objects.using(used_alias).create(
                entry=journal_entry,
                account=account_revenue,
                line_description=f"إيراد بيع سيارة {car.vin}",
                debit=Decimal('0'),
                credit=sale_price,
                currency=car.currency,
                car=car,
            )

            cogs_value = car.total_cost_price or Decimal('0')
            if cogs_value > Decimal('0'):
                JournalEntryLine.objects.using(used_alias).create(
                    entry=journal_entry,
                    account=account_cogs,
                    line_description=f"إخراج تكلفة السيارة {car.vin}",
                    debit=cogs_value,
                    credit=Decimal('0'),
                    currency=car.currency,
                    car=car,
                )
                JournalEntryLine.objects.using(used_alias).create(
                    entry=journal_entry,
                    account=account_inventory,
                    line_description=f"تخفيض مخزون السيارة {car.vin}",
                    debit=Decimal('0'),
                    credit=cogs_value,
                    currency=car.currency,
                    car=car,
                )

            first_due_date = schedule_rows[0]['due_date'] if schedule_rows else None
            audit_message = (
                f"قام الموظف [{getattr(actor, 'username', 'system')}] ببيع السيارة [{car.vin}] "
                f"للعميل [{customer.name}] بقيمة [{sale_price}]، تم دفع [{amount_paid}] والمتبقي [{remaining_balance}]"
            )

            OperationLog.objects.using(used_alias).create(
                operation=audit_message[:255],
                user_id=actor_id,
            )

            AuditLog.objects.using(used_alias).create(
                user_id=actor_id,
                tenant_id=used_alias.replace('tenant_', ''),
                action='credit_sale',
                target_model='Sale',
                target_pk=str(sale.pk),
                before_data=None,
                after_data={
                    'message': audit_message,
                    'car_id': car.pk,
                    'car_vin': car.vin,
                    'customer_id': customer.pk,
                    'sale_id': sale.pk,
                    'sale_price': str(sale_price),
                    'down_payment': str(amount_paid),
                    'remaining_balance': str(remaining_balance),
                    'currency': car.currency,
                    'currency_rate': str(fx_rate),
                    'schedule_count': len(schedule_rows),
                    'first_due_date': first_due_date.isoformat() if first_due_date else '',
                    'request_path': request_path,
                },
                ip_address=ip_address or '',
                device_type=device_type or '',
                browser=browser or '',
                geo_location=geo_location or '',
                request_path=request_path or '',
            )

        return CreditSaleResult(
            sale=sale,
            receipt_voucher=receipt_voucher,
            journal_entry=journal_entry,
        )

    @staticmethod
    def allocate_payment_to_installments(*, tenant_alias, sale_id, payment_amount):
        used_alias = (tenant_alias or '').strip()
        if not used_alias.startswith('tenant_'):
            return

        remaining_to_apply = _as_decimal(payment_amount)
        if remaining_to_apply <= Decimal('0'):
            return

        sale = Sale.objects.using(used_alias).select_related('car').filter(pk=sale_id).first()
        if sale is None:
            return

        installments = list(
            SaleInstallment.objects.using(used_alias)
            .filter(sale_id=sale.pk)
            .order_by('due_date', 'installment_order', 'id')
        )

        if not installments and sale.sale_price > sale.amount_paid:
            fallback_due = sale.debt_due_date or timezone.localdate()
            outstanding_now = sale.sale_price - sale.amount_paid + remaining_to_apply
            fallback = SaleInstallment.objects.using(used_alias).create(
                sale_id=sale.pk,
                installment_order=1,
                due_date=fallback_due,
                amount=outstanding_now,
                note='قسط افتراضي لبيع قديم قبل تفعيل جدول الأقساط.',
            )
            installments = [fallback]

        updated_installments = []
        for installment in installments:
            installment_remaining = installment.remaining_amount
            if installment_remaining <= Decimal('0'):
                if installment.status != SaleInstallment.STATUS_PAID:
                    installment.status = SaleInstallment.STATUS_PAID
                    installment.paid_amount = installment.amount
                    updated_installments.append(installment)
                continue

            if remaining_to_apply <= Decimal('0'):
                break

            applied = installment_remaining if installment_remaining <= remaining_to_apply else remaining_to_apply
            installment.paid_amount = installment.paid_amount + applied
            remaining_to_apply -= applied

            if installment.paid_amount >= installment.amount:
                installment.status = SaleInstallment.STATUS_PAID
            else:
                installment.status = SaleInstallment.STATUS_PARTIAL
            updated_installments.append(installment)

        for installment in updated_installments:
            installment.save(using=used_alias, update_fields=['paid_amount', 'status'])

        next_installment = (
            SaleInstallment.objects.using(used_alias)
            .filter(sale_id=sale.pk)
            .exclude(status=SaleInstallment.STATUS_PAID)
            .order_by('due_date', 'installment_order', 'id')
            .first()
        )

        next_due_date = next_installment.due_date if next_installment is not None else None
        if sale.debt_due_date != next_due_date:
            sale.debt_due_date = next_due_date
            sale.save(using=used_alias, update_fields=['debt_due_date'])
