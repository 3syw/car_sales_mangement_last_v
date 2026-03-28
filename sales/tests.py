from django.http import HttpResponse
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from .models import AuditLog, Car, Customer, FinanceVoucher, JournalEntry, JournalEntryLine, Sale, SaleInstallment
from .models import InterfaceAccess
from .api_serializers import FinanceVoucherSerializer
from .middleware import OperationLogMiddleware
from .services import SalesService
from .tenant_database import ensure_tenant_connection
from .tenant_context import clear_current_tenant, set_current_tenant


TEST_TENANT_ID = 'servicecredittests'
TEST_TENANT_ALIAS = ensure_tenant_connection(TEST_TENANT_ID) or f'tenant_{TEST_TENANT_ID}'
ISOLATION_TENANT_A = 'isolationtenanta'
ISOLATION_TENANT_B = 'isolationtenantb'
ISOLATION_ALIAS_A = ensure_tenant_connection(ISOLATION_TENANT_A) or f'tenant_{ISOLATION_TENANT_A}'
ISOLATION_ALIAS_B = ensure_tenant_connection(ISOLATION_TENANT_B) or f'tenant_{ISOLATION_TENANT_B}'

class BasicTests(TestCase):
    def test_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get('/dashboard/')
        self.assertIn(response.status_code, (302, 403))


class SalesServiceTests(TestCase):
    databases = {'default', TEST_TENANT_ALIAS}
    tenant_alias = TEST_TENANT_ALIAS

    def setUp(self):
        set_current_tenant(tenant_id=TEST_TENANT_ID, db_alias=self.tenant_alias)
        SaleInstallment.objects.using(self.tenant_alias).all().delete()
        JournalEntryLine.objects.using(self.tenant_alias).all().delete()
        JournalEntry.objects.using(self.tenant_alias).all().delete()
        FinanceVoucher.objects.using(self.tenant_alias).all().delete()
        Sale.objects.using(self.tenant_alias).all().delete()
        Customer.objects.using(self.tenant_alias).all().delete()
        Car.objects.using(self.tenant_alias).all().delete()

    def tearDown(self):
        clear_current_tenant()

    def _create_car(self, vin_sequence=1):
        vin = f"TESTVIN{vin_sequence:010d}"
        return Car.objects.using(self.tenant_alias).create(
            brand='Toyota',
            model_name='Camry',
            vin=vin,
            year=2024,
            cost_price=Decimal('30000'),
            selling_price=Decimal('50000'),
            currency='SR',
        )

    def test_execute_credit_sale_creates_sale_installments_and_journal(self):
        car = self._create_car(vin_sequence=1)
        first_due = timezone.localdate() + timedelta(days=30)
        second_due = timezone.localdate() + timedelta(days=60)

        result = SalesService.execute_credit_sale(
            tenant_alias=self.tenant_alias,
            car_id=car.pk,
            customer_name='عميل اختبار',
            customer_phone='0500000000',
            customer_national_id='ID-10001',
            total_sale_price=Decimal('50000'),
            down_payment=Decimal('10000'),
            payment_schedule=[
                {'due_date': first_due.isoformat(), 'amount': '20000'},
                {'due_date': second_due.isoformat(), 'amount': '20000'},
            ],
            sale_contract_image='sale_contracts/test_contract_1.pdf',
            currency_rate=Decimal('1'),
        )

        sale = result.sale
        car.refresh_from_db(using=self.tenant_alias)

        self.assertTrue(car.is_sold)
        self.assertEqual(Sale.objects.using(self.tenant_alias).count(), 1)
        self.assertEqual(sale.debt_due_date, first_due)

        installments = list(
            SaleInstallment.objects.using(self.tenant_alias)
            .filter(sale_id=sale.pk)
            .order_by('installment_order')
        )
        self.assertEqual(len(installments), 2)
        self.assertEqual(installments[0].amount + installments[1].amount, Decimal('40000'))
        self.assertEqual(installments[0].status, SaleInstallment.STATUS_PENDING)

        self.assertEqual(
            FinanceVoucher.objects.using(self.tenant_alias).filter(voucher_type='receipt').count(),
            1,
        )

        self.assertEqual(
            JournalEntry.objects.using(self.tenant_alias).filter(source_model='Sale', source_pk=str(sale.pk)).count(),
            1,
        )
        self.assertEqual(
            JournalEntry.objects.using(self.tenant_alias).filter(source_model='FinanceVoucher').count(),
            0,
        )
        self.assertEqual(
            JournalEntryLine.objects.using(self.tenant_alias).filter(entry=result.journal_entry).count(),
            5,
        )

    def test_execute_credit_sale_rolls_back_on_mid_transaction_failure(self):
        car = self._create_car(vin_sequence=2)

        with patch('sales.services.sales_service._next_journal_entry_number', side_effect=RuntimeError('forced-failure')):
            with self.assertRaises(RuntimeError):
                SalesService.execute_credit_sale(
                    tenant_alias=self.tenant_alias,
                    car_id=car.pk,
                    customer_name='عميل فشل',
                    customer_phone='0511111111',
                    customer_national_id='ID-10002',
                    total_sale_price=Decimal('50000'),
                    down_payment=Decimal('5000'),
                    payment_schedule=[
                        {
                            'due_date': (timezone.localdate() + timedelta(days=30)).isoformat(),
                            'amount': '45000',
                        }
                    ],
                    sale_contract_image='sale_contracts/test_contract_2.pdf',
                    currency_rate=Decimal('1'),
                )

        car.refresh_from_db(using=self.tenant_alias)
        self.assertFalse(car.is_sold)
        self.assertEqual(Sale.objects.using(self.tenant_alias).count(), 0)
        self.assertEqual(Customer.objects.using(self.tenant_alias).count(), 0)
        self.assertEqual(SaleInstallment.objects.using(self.tenant_alias).count(), 0)
        self.assertEqual(FinanceVoucher.objects.using(self.tenant_alias).count(), 0)
        self.assertEqual(JournalEntry.objects.using(self.tenant_alias).count(), 0)


class TenantIsolationAPITests(TestCase):
    databases = {'default', ISOLATION_ALIAS_A, ISOLATION_ALIAS_B}

    def setUp(self):
        user_model = get_user_model()
        user_model.objects.using(ISOLATION_ALIAS_A).all().delete()
        user_model.objects.using(ISOLATION_ALIAS_B).all().delete()

        self.user_a = user_model.objects.db_manager(ISOLATION_ALIAS_A).create_user(
            username='tenant_user_a',
            password='StrongPass#123',
            is_active=True,
        )
        self.user_b = user_model.objects.db_manager(ISOLATION_ALIAS_B).create_user(
            username='tenant_user_b',
            password='StrongPass#123',
            is_active=True,
        )

        access = AccessToken()
        access['user_id'] = self.user_a.pk
        access['tenant_id'] = ISOLATION_TENANT_A
        access['tenant_alias'] = ISOLATION_ALIAS_A
        access['username'] = self.user_a.username
        self.access_token_a = str(access)
        self.client = APIClient()

    def test_auth_me_rejects_mismatched_tenant_header(self):
        response = self.client.get(
            '/api/auth/me/',
            HTTP_AUTHORIZATION=f'Bearer {self.access_token_a}',
            HTTP_X_TENANT_ID=ISOLATION_TENANT_B,
        )
        self.assertEqual(response.status_code, 401)

    def test_auth_me_accepts_matching_tenant_header(self):
        response = self.client.get(
            '/api/auth/me/',
            HTTP_AUTHORIZATION=f'Bearer {self.access_token_a}',
            HTTP_X_TENANT_ID=ISOLATION_TENANT_A,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.get('tenant_id'), ISOLATION_TENANT_A)
        self.assertEqual(response.data.get('username'), self.user_a.username)


class FinancePrivilegesAndSanitizationTests(TestCase):
    databases = {'default', ISOLATION_ALIAS_A}

    def setUp(self):
        user_model = get_user_model()
        user_model.objects.using(ISOLATION_ALIAS_A).all().delete()
        InterfaceAccess.objects.using(ISOLATION_ALIAS_A).all().delete()
        FinanceVoucher.objects.using(ISOLATION_ALIAS_A).all().delete()

        self.staff_user = user_model.objects.db_manager(ISOLATION_ALIAS_A).create_user(
            username='finance_staff',
            password='StrongPass#123',
            is_active=True,
            is_staff=False,
        )
        self.manager_user = user_model.objects.db_manager(ISOLATION_ALIAS_A).create_user(
            username='finance_manager',
            password='StrongPass#123',
            is_active=True,
            is_staff=False,
        )

        self.staff_access = InterfaceAccess.objects.using(ISOLATION_ALIAS_A).create(
            user=self.staff_user,
            can_access_system_users=False,
            can_access_reports=True,
        )
        self.manager_access = InterfaceAccess.objects.using(ISOLATION_ALIAS_A).create(
            user=self.manager_user,
            can_access_system_users=True,
            can_access_reports=True,
        )

        self.client = APIClient()

    def tearDown(self):
        clear_current_tenant()

    def _token_for(self, user):
        access = AccessToken()
        access['user_id'] = user.pk
        access['tenant_id'] = ISOLATION_TENANT_A
        access['tenant_alias'] = ISOLATION_ALIAS_A
        access['username'] = user.username
        return str(access)

    def test_finance_voucher_create_requires_manager_privilege(self):
        payload = {
            'voucher_type': 'receipt',
            'voucher_number': 'VCH-0001',
            'voucher_date': timezone.localdate().isoformat(),
            'person_name': 'عميل اختبار',
            'amount': '1500.00',
            'currency': 'SR',
            'reason': 'تحصيل دفعة',
            'debit_account': 'cash_box',
            'credit_account': 'cash_box',
        }

        staff_response = self.client.post(
            '/api/finance-vouchers/',
            payload,
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self._token_for(self.staff_user)}',
            HTTP_X_TENANT_ID=ISOLATION_TENANT_A,
        )
        self.assertEqual(staff_response.status_code, 403)

        manager_response = self.client.post(
            '/api/finance-vouchers/',
            payload | {'voucher_number': 'VCH-0002'},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self._token_for(self.manager_user)}',
            HTTP_X_TENANT_ID=ISOLATION_TENANT_A,
        )
        self.assertEqual(manager_response.status_code, 201)

    def test_finance_voucher_serializer_strips_html_tags(self):
        set_current_tenant(tenant_id=ISOLATION_TENANT_A, db_alias=ISOLATION_ALIAS_A)
        serializer = FinanceVoucherSerializer(data={
            'voucher_type': 'receipt',
            'voucher_number': 'VCH-1001',
            'voucher_date': timezone.localdate().isoformat(),
            'person_name': '<script>alert(1)</script>أحمد',
            'amount': '100.00',
            'currency': 'SR',
            'reason': '<b>دفعة</b> <img src=x onerror=alert(2)>',
            'debit_account': 'cash_box',
            'credit_account': 'cash_box',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['person_name'], 'alert(1)أحمد')
        self.assertEqual(serializer.validated_data['reason'], 'دفعة')

    def test_finance_voucher_delete_soft_deletes_and_creates_reversal(self):
        voucher = FinanceVoucher.objects.using(ISOLATION_ALIAS_A).create(
            voucher_type='receipt',
            voucher_number='VCH-DELETE-01',
            voucher_date=timezone.localdate(),
            person_name='عميل إلغاء',
            amount=Decimal('500.00'),
            currency='SR',
            reason='سند أصلي',
            debit_account='cash_box',
            credit_account='bank',
        )

        response = self.client.delete(
            f'/api/finance-vouchers/{voucher.pk}/',
            data={'deletion_note': 'إلغاء محاسبي'},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {self._token_for(self.manager_user)}',
            HTTP_X_TENANT_ID=ISOLATION_TENANT_A,
        )
        self.assertEqual(response.status_code, 200)

        voucher.refresh_from_db(using=ISOLATION_ALIAS_A)
        self.assertTrue(voucher.is_deleted)
        self.assertEqual(voucher.deleted_by, self.manager_user.username)

        reversal = FinanceVoucher.objects.using(ISOLATION_ALIAS_A).get(reversed_from=voucher)
        self.assertFalse(reversal.is_deleted)
        self.assertEqual(reversal.debit_account, voucher.credit_account)
        self.assertEqual(reversal.credit_account, voucher.debit_account)


class SecurityExportAlertTests(TestCase):
    databases = {'default', ISOLATION_ALIAS_A}

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        user_model = get_user_model()
        user_model.objects.using(ISOLATION_ALIAS_A).all().delete()
        AuditLog.objects.using(ISOLATION_ALIAS_A).all().delete()
        self.user = user_model.objects.db_manager(ISOLATION_ALIAS_A).create_user(
            username='export_monitor_user',
            password='StrongPass#123',
            is_active=True,
        )

    def tearDown(self):
        cache.clear()
        clear_current_tenant()

    @override_settings(SECURITY_EXPORT_ALERT_THRESHOLD=2, SECURITY_EXPORT_WINDOW_SECONDS=600)
    def test_export_burst_creates_single_security_alert(self):
        def _get_response(_request):
            response = HttpResponse('csv-data', status=200)
            response['Content-Disposition'] = 'attachment; filename="audit.csv"'
            return response

        middleware = OperationLogMiddleware(_get_response)

        with patch('sales.middleware.publish_tenant_event') as publish_mock:
            emitted = []
            for _ in range(2):
                set_current_tenant(tenant_id=ISOLATION_TENANT_A, db_alias=ISOLATION_ALIAS_A)
                request = self.factory.get(
                    '/reports/audit-logs/export/csv/',
                    HTTP_USER_AGENT='Mozilla/5.0',
                    HTTP_CF_IPCOUNTRY='SA',
                    REMOTE_ADDR='127.0.0.1',
                )
                request.user = self.user
                request.session = {'tenant_id': ISOLATION_TENANT_A}
                request.tenant_id = ISOLATION_TENANT_A
                request.tenant_db_alias = ISOLATION_ALIAS_A
                response = _get_response(request)
                emitted.append(middleware._maybe_emit_export_security_alert(request, response))

            self.assertEqual(emitted, [False, True])

        alerts = AuditLog.objects.using(ISOLATION_ALIAS_A).filter(
            action='security_alert',
            target_model='ExportActivity',
            user=self.user,
        )
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(publish_mock.call_count, 1)

        payload = alerts.first().after_data or {}
        self.assertEqual(payload.get('alert_type'), 'export_burst')
        self.assertEqual(payload.get('export_count'), 2)

