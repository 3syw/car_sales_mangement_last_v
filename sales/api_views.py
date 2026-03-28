from decimal import Decimal
from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError

from .auth_api import CurrentUserAPIView, TenantTokenObtainPairView, TenantTokenRefreshView
from .api_serializers import (
    AuditLogSerializer,
    CarSerializer,
    DBIsolationTaskSerializer,
    DebtPaymentSerializer,
    FinancialConsistencyTaskSerializer,
    FinanceVoucherSerializer,
    SaleProcessSerializer,
    SaleSerializer,
    TenantBackupTaskSerializer,
    TenantSnapshotTaskSerializer,
)
from .models import AuditLog, Car, DebtPayment, FinanceVoucher, Sale
from .services import AsyncService, ReportService, SalesService
from .tenant_context import get_current_tenant_db_alias, set_current_tenant
from .tenant_database import ensure_tenant_connection, normalize_tenant_id
from .tenant_registry import get_cached_tenant_metadata
from .throttling import (
    AuthRefreshBurstThrottle,
    AuthRefreshSustainedThrottle,
    AuthTokenBurstThrottle,
    AuthTokenSustainedThrottle,
)


def _resolve_tenant_alias(request):
    header_tenant_id = normalize_tenant_id(request.headers.get('X-Tenant-ID') or request.META.get('HTTP_X_TENANT_ID'))
    request_tenant_id = normalize_tenant_id(getattr(request, 'tenant_id', ''))
    session_tenant_id = normalize_tenant_id(request.session.get('tenant_id'))

    if request_tenant_id:
        if header_tenant_id and header_tenant_id != request_tenant_id:
            raise PermissionDenied('بيئة المعرض في الترويسة لا تطابق التوكن.')

        alias = (getattr(request, 'tenant_db_alias', '') or '').strip()
        if not alias.startswith('tenant_'):
            alias = ensure_tenant_connection(request_tenant_id) or ''
        if alias.startswith('tenant_'):
            set_current_tenant(request_tenant_id, alias)
            return alias
        raise PermissionDenied('لا يمكن تهيئة بيئة المعرض من بيانات التوكن.')

    if session_tenant_id:
        if header_tenant_id and header_tenant_id != session_tenant_id:
            raise PermissionDenied('لا يمكن تغيير بيئة المعرض عبر الترويسة أثناء الجلسة النشطة.')
        metadata = get_cached_tenant_metadata(session_tenant_id)
        if metadata and metadata.get('is_active'):
            alias = ensure_tenant_connection(session_tenant_id)
            if alias:
                set_current_tenant(session_tenant_id, alias)
                return alias
        raise PermissionDenied('بيئة المعرض في الجلسة غير صالحة.')

    if header_tenant_id:
        raise PermissionDenied('الترويسة X-Tenant-ID وحدها غير كافية بدون سياق مصادقة موثوق.')

    alias = (get_current_tenant_db_alias() or '').strip()
    if alias.startswith('tenant_'):
        return alias

    raise PermissionDenied('لا توجد بيئة معرض مفعلة لواجهات API.')


def _classify_device(user_agent):
    ua = (user_agent or '').lower()
    for keyword in ['iphone', 'android', 'mobile', 'ipad']:
        if keyword in ua:
            return 'mobile'
    return 'desktop' if ua else ''


def _classify_browser(user_agent):
    ua = (user_agent or '').lower()
    if 'edg/' in ua:
        return 'Edge'
    if 'chrome/' in ua and 'edg/' not in ua:
        return 'Chrome'
    if 'firefox/' in ua:
        return 'Firefox'
    if 'safari/' in ua and 'chrome/' not in ua:
        return 'Safari'
    return ''


def _require_superuser(user):
    if user is None or not user.is_authenticated or not user.is_superuser:
        raise PermissionDenied('يتطلب هذا الإجراء صلاحية المشرف العام.')


def _is_tenant_manager(request, alias):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True

    from .models import InterfaceAccess

    access, _ = InterfaceAccess.objects.using(alias).get_or_create(user=user)
    return bool(access.can_access_system_users)


def _require_tenant_manager(request, alias, action_label='هذا الإجراء'):
    if not _is_tenant_manager(request, alias):
        raise PermissionDenied(f'{action_label} يتطلب صلاحية مدير المعرض.')


class TenantScopedViewMixin:
    def resolve_tenant_alias(self):
        alias = _resolve_tenant_alias(self.request)
        self.request.tenant_db_alias = alias
        self.request.tenant_id = alias[len('tenant_'):] if alias.startswith('tenant_') else ''
        return alias

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['tenant_alias'] = getattr(self.request, 'tenant_db_alias', '') or self.resolve_tenant_alias()
        return context


class CarViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    serializer_class = CarSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        alias = self.resolve_tenant_alias()
        queryset = Car.objects.using(alias).all().order_by('-created_at', '-id')

        is_sold = (self.request.query_params.get('is_sold') or '').strip().lower()
        if is_sold in {'true', '1', 'yes'}:
            queryset = queryset.filter(is_sold=True)
        elif is_sold in {'false', '0', 'no'}:
            queryset = queryset.filter(is_sold=False)

        search_text = (self.request.query_params.get('q') or '').strip()
        if search_text:
            queryset = queryset.filter(
                Q(vin__icontains=search_text)
                | Q(brand__icontains=search_text)
                | Q(model_name__icontains=search_text)
            )

        return queryset

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        _require_tenant_manager(request, alias, 'حذف السيارات')
        return super().destroy(request, *args, **kwargs)


class SaleViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SaleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        alias = self.resolve_tenant_alias()
        queryset = (
            Sale.objects.using(alias)
            .select_related('car', 'customer', 'sales_employee')
            .prefetch_related('installments')
            .order_by('-sale_date', '-id')
        )

        search_text = (self.request.query_params.get('q') or '').strip()
        if search_text:
            queryset = queryset.filter(
                Q(car__vin__icontains=search_text)
                | Q(customer__name__icontains=search_text)
                | Q(customer__national_id__icontains=search_text)
            )

        return queryset


class FinanceVoucherViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    serializer_class = FinanceVoucherSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        alias = self.resolve_tenant_alias()
        queryset = (
            FinanceVoucher.objects.using(alias)
            .filter(is_deleted=False)
            .select_related('linked_car', 'financial_container')
            .order_by('-voucher_date', '-created_at')
        )

        voucher_type = (self.request.query_params.get('voucher_type') or '').strip().lower()
        if voucher_type:
            queryset = queryset.filter(voucher_type=voucher_type)

        search_text = (self.request.query_params.get('q') or '').strip()
        if search_text:
            queryset = queryset.filter(
                Q(voucher_number__icontains=search_text)
                | Q(person_name__icontains=search_text)
                | Q(reason__icontains=search_text)
            )

        return queryset

    def create(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        _require_tenant_manager(request, alias, 'إضافة السندات المالية')
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        _require_tenant_manager(request, alias, 'تعديل السندات المالية')
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        _require_tenant_manager(request, alias, 'تعديل السندات المالية')
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        _require_tenant_manager(request, alias, 'حذف السندات المالية')
        voucher = self.get_object()
        note = (request.data.get('deletion_note') or '').strip() if hasattr(request, 'data') else ''
        if not note:
            note = 'تم الإلغاء بواسطة المدير مع إنشاء قيد عكسي.'

        with transaction.atomic(using=alias):
            if voucher.is_deleted:
                return Response({'detail': 'السند ملغي مسبقاً.'}, status=status.HTTP_200_OK)

            reversal_number = f"REV-{voucher.voucher_number}-{datetime.now().strftime('%H%M%S')}"
            reversal = FinanceVoucher.objects.using(alias).create(
                voucher_type=voucher.voucher_type,
                voucher_number=reversal_number,
                voucher_date=timezone.localdate(),
                person_name=voucher.person_name,
                amount=voucher.amount,
                currency=voucher.currency,
                reason=f"قيد عكسي للسند {voucher.voucher_number}: {note}",
                linked_car=voucher.linked_car,
                financial_container=voucher.financial_container,
                debit_account=voucher.credit_account,
                credit_account=voucher.debit_account,
                reversed_from=voucher,
            )

            voucher.is_deleted = True
            voucher.deleted_at = timezone.now()
            voucher.deleted_by = getattr(request.user, 'username', '')[:150]
            voucher.deletion_note = note[:255]
            voucher.save(using=alias, update_fields=['is_deleted', 'deleted_at', 'deleted_by', 'deletion_note'])

            AuditLog.objects.using(alias).create(
                user=request.user if request.user.is_authenticated else None,
                tenant_id=getattr(request, 'tenant_id', ''),
                action='soft_delete',
                target_model='FinanceVoucher',
                target_pk=str(voucher.pk),
                before_data={
                    'voucher_number': voucher.voucher_number,
                    'amount': str(voucher.amount),
                    'debit_account': voucher.debit_account,
                    'credit_account': voucher.credit_account,
                },
                after_data={
                    'is_deleted': True,
                    'deletion_note': voucher.deletion_note,
                    'reversal_voucher_number': reversal.voucher_number,
                },
                ip_address=(request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('REMOTE_ADDR') or ''),
                device_type=_classify_device(request.META.get('HTTP_USER_AGENT') or ''),
                browser=_classify_browser(request.META.get('HTTP_USER_AGENT') or ''),
                geo_location=(request.META.get('HTTP_CF_IPCOUNTRY') or request.META.get('HTTP_X_APPENGINE_COUNTRY') or ''),
                request_path=request.path,
            )

        return Response({
            'status': 'soft_deleted',
            'voucher_id': voucher.pk,
            'reversal_voucher_id': reversal.pk,
            'reversal_voucher_number': reversal.voucher_number,
        }, status=status.HTTP_200_OK)


class DebtPaymentViewSet(TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = DebtPaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        alias = self.resolve_tenant_alias()
        queryset = (
            DebtPayment.objects.using(alias)
            .filter(is_deleted=False)
            .select_related('sale__car', 'sale__customer')
            .order_by('-payment_date', '-id')
        )

        sale_id = (self.request.query_params.get('sale_id') or '').strip()
        if sale_id.isdigit():
            queryset = queryset.filter(sale_id=int(sale_id))

        return queryset

    def create(self, request, *args, **kwargs):
        alias = self.resolve_tenant_alias()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        with transaction.atomic(using=alias):
            sale = (
                Sale.objects.using(alias)
                .select_for_update()
                .select_related('car', 'customer')
                .filter(pk=validated['sale'].pk)
                .first()
            )
            if sale is None:
                raise ValidationError({'sale': 'عملية البيع غير موجودة.'})

            paid_amount = validated['paid_amount']
            if paid_amount <= Decimal('0'):
                raise ValidationError({'paid_amount': 'المبلغ المسدد يجب أن يكون أكبر من صفر.'})

            if paid_amount > sale.remaining_amount:
                raise ValidationError({'paid_amount': 'المبلغ المسدد لا يمكن أن يتجاوز المبلغ المتبقي.'})

            if DebtPayment.objects.using(alias).filter(receipt_number=validated['receipt_number']).exists():
                raise ValidationError({'receipt_number': 'رقم السند مستخدم مسبقاً.'})

            payment = DebtPayment.objects.using(alias).create(
                sale=sale,
                receipt_number=validated['receipt_number'],
                payment_date=validated['payment_date'],
                paid_amount=paid_amount,
            )

            FinanceVoucher.objects.using(alias).get_or_create(
                voucher_number=payment.receipt_number,
                defaults={
                    'voucher_type': 'settlement',
                    'voucher_date': payment.payment_date,
                    'person_name': sale.customer.name,
                    'amount': payment.paid_amount,
                    'currency': sale.car.currency,
                    'reason': f'تسديد مديونية سيارة {sale.car.brand} {sale.car.model_name}',
                    'linked_car': sale.car,
                    'debit_account': FinanceVoucher.ACCOUNT_CASH_BOX,
                    'credit_account': FinanceVoucher.ACCOUNT_CASH_BOX,
                },
            )

            sale.amount_paid = (sale.amount_paid or Decimal('0')) + paid_amount
            update_fields = ['amount_paid']
            if sale.amount_paid >= sale.sale_price and sale.debt_due_date is not None:
                sale.debt_due_date = None
                update_fields.append('debt_due_date')
            sale.save(using=alias, update_fields=update_fields)

            SalesService.allocate_payment_to_installments(
                tenant_alias=alias,
                sale_id=sale.pk,
                payment_amount=paid_amount,
            )

        output = self.get_serializer(payment)
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)


class AuditLogViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        alias = self.resolve_tenant_alias()
        queryset = AuditLog.objects.using(alias).select_related('user').order_by('-timestamp')

        action = (self.request.query_params.get('action') or '').strip()
        if action:
            queryset = queryset.filter(action=action)

        target_model = (self.request.query_params.get('target_model') or '').strip()
        if target_model:
            queryset = queryset.filter(target_model__iexact=target_model)

        return queryset


class SaleProcessAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        alias = _resolve_tenant_alias(request)
        serializer = SaleProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        user_agent = request.META.get('HTTP_USER_AGENT') or ''
        try:
            result = SalesService.execute_credit_sale(
                tenant_alias=alias,
                car_id=payload['car_id'],
                customer_name=payload['customer_name'],
                customer_phone=payload['customer_phone'],
                customer_national_id=payload['customer_national_id'],
                total_sale_price=payload['sale_price'],
                down_payment=payload['amount_paid'],
                payment_schedule=payload.get('payment_schedule', []),
                debt_due_date=payload.get('debt_due_date'),
                sale_contract_image=payload.get('sale_contract_image'),
                actor=request.user,
                currency_rate=payload.get('currency_rate'),
                financial_container_id=payload.get('financial_container_id'),
                request_path=request.path,
                ip_address=request.META.get('REMOTE_ADDR', ''),
                device_type=_classify_device(user_agent),
                browser=_classify_browser(user_agent),
                geo_location=(request.META.get('HTTP_CF_IPCOUNTRY') or request.META.get('HTTP_X_APPENGINE_COUNTRY') or ''),
            )
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise ValidationError(exc.message_dict)
            raise ValidationError(exc.messages)

        return Response({
            'status': 'success',
            'sale_id': result.sale.pk,
            'journal_entry_id': result.journal_entry.pk,
            'receipt_voucher_id': result.receipt_voucher.pk if result.receipt_voucher else None,
        }, status=status.HTTP_201_CREATED)


class ReportsSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        alias = _resolve_tenant_alias(request)

        sales = list(Sale.objects.using(alias).select_related('car').all())
        total_sales_by_currency = {}
        total_profit_by_currency = {}
        outstanding_by_currency = {}

        for sale in sales:
            currency = getattr(sale.car, 'currency', 'SR')
            total_sales_by_currency[currency] = total_sales_by_currency.get(currency, Decimal('0')) + (sale.sale_price or Decimal('0'))
            total_profit_by_currency[currency] = total_profit_by_currency.get(currency, Decimal('0')) + (sale.actual_profit or Decimal('0'))
            outstanding_by_currency[currency] = outstanding_by_currency.get(currency, Decimal('0')) + (sale.remaining_amount or Decimal('0'))

        stale_30 = ReportService.stale_cars(tenant_alias=alias, days_threshold=30).count()
        stale_60 = ReportService.stale_cars(tenant_alias=alias, days_threshold=60).count()
        stale_90 = ReportService.stale_cars(tenant_alias=alias, days_threshold=90).count()

        performance = ReportService.showroom_performance(tenant_alias=alias)

        return Response({
            'sold_count': len(sales),
            'available_count': Car.objects.using(alias).filter(is_sold=False).count(),
            'inventory_turnover': str(ReportService.inventory_turnover(tenant_alias=alias)),
            'average_days_in_inventory': performance.get('average_days_in_inventory', 0),
            'stale_cars': {
                '30_plus': stale_30,
                '60_plus': stale_60,
                '90_plus': stale_90,
            },
            'totals': {
                'sales_by_currency': {key: str(value) for key, value in total_sales_by_currency.items()},
                'profit_by_currency': {key: str(value) for key, value in total_profit_by_currency.items()},
                'outstanding_by_currency': {key: str(value) for key, value in outstanding_by_currency.items()},
            },
        })


class QueueFinancialConsistencyTaskAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_superuser(request.user)

        serializer = FinancialConsistencyTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            async_result = AsyncService.queue_financial_consistency_report(
                tenant_id=payload.get('tenant_id', ''),
                report_path=payload.get('report_path', ''),
            )
        except Exception as exc:
            raise ValidationError({'detail': f'تعذر جدولة مهمة فحص الاتساق المالي: {exc}'})

        return Response({
            'status': 'queued',
            'task_id': async_result.id,
            'task_name': 'financial_consistency_report',
        }, status=status.HTTP_202_ACCEPTED)


class QueueTenantBackupTaskAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_superuser(request.user)

        serializer = TenantBackupTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            async_result = AsyncService.queue_tenant_backup(
                tenant_id=payload['tenant_id'],
                actor=payload.get('actor') or request.user.username,
            )
        except Exception as exc:
            raise ValidationError({'detail': f'تعذر جدولة مهمة النسخ الاحتياطي: {exc}'})

        return Response({
            'status': 'queued',
            'task_id': async_result.id,
            'task_name': 'tenant_backup',
        }, status=status.HTTP_202_ACCEPTED)


class QueueDBIsolationAuditTaskAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_superuser(request.user)

        serializer = DBIsolationTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            async_result = AsyncService.queue_db_isolation_audit(
                cleanup=payload.get('cleanup', False),
                force=payload.get('force', False),
                skip_backup=payload.get('skip_backup', False),
                report_path=payload.get('report_path', ''),
            )
        except Exception as exc:
            raise ValidationError({'detail': f'تعذر جدولة مهمة تدقيق العزل: {exc}'})

        return Response({
            'status': 'queued',
            'task_id': async_result.id,
            'task_name': 'db_isolation_audit',
        }, status=status.HTTP_202_ACCEPTED)


class QueueTenantSnapshotTaskAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_superuser(request.user)

        serializer = TenantSnapshotTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            async_result = AsyncService.queue_reports_snapshot(tenant_id=payload['tenant_id'])
        except Exception as exc:
            raise ValidationError({'detail': f'تعذر جدولة مهمة توليد ملخص التقارير: {exc}'})

        return Response({
            'status': 'queued',
            'task_id': async_result.id,
            'task_name': 'tenant_reports_snapshot',
        }, status=status.HTTP_202_ACCEPTED)


class TaskStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        _require_superuser(request.user)
        return Response(AsyncService.get_task_status(task_id))


class AuthTokenAPIView(TenantTokenObtainPairView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthTokenBurstThrottle, AuthTokenSustainedThrottle]


class AuthRefreshAPIView(TenantTokenRefreshView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRefreshBurstThrottle, AuthRefreshSustainedThrottle]


class AuthMeAPIView(CurrentUserAPIView):
    permission_classes = [IsAuthenticated]
