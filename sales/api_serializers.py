from decimal import Decimal
import re

from rest_framework import serializers

from .models import AuditLog, Car, DebtPayment, FinanceVoucher, Sale, SaleInstallment
from .sanitization import sanitize_plain_text


PHONE_RE = re.compile(r'^[0-9+()\-\s]{6,20}$')


class TenantBoundModelSerializer(serializers.ModelSerializer):
    def _tenant_alias(self):
        alias = (self.context.get('tenant_alias') or '').strip()
        if alias.startswith('tenant_'):
            return alias

        request = self.context.get('request')
        request_alias = (getattr(request, 'tenant_db_alias', '') or '').strip() if request is not None else ''
        if request_alias.startswith('tenant_'):
            return request_alias

        raise serializers.ValidationError('لا توجد بيئة معرض مفعلة لعملية الحفظ.')

    def create(self, validated_data):
        return self.Meta.model.objects.using(self._tenant_alias()).create(**validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save(using=self._tenant_alias())
        return instance


class SaleInstallmentSerializer(serializers.ModelSerializer):
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = SaleInstallment
        fields = [
            'id',
            'installment_order',
            'due_date',
            'amount',
            'paid_amount',
            'remaining_amount',
            'status',
            'note',
        ]

    def get_remaining_amount(self, obj):
        return obj.remaining_amount


class CarSerializer(TenantBoundModelSerializer):
    total_cost_price = serializers.SerializerMethodField()
    expected_profit = serializers.SerializerMethodField()

    class Meta:
        model = Car
        fields = [
            'id',
            'brand',
            'model_name',
            'vin',
            'year',
            'cost_price',
            'customs_cost',
            'transport_cost',
            'commission_cost',
            'selling_price',
            'image',
            'contract_image',
            'insurance_expiry',
            'registration_expiry',
            'currency',
            'is_sold',
            'created_at',
            'total_cost_price',
            'expected_profit',
        ]
        read_only_fields = ['id', 'created_at', 'total_cost_price', 'expected_profit']

    def get_total_cost_price(self, obj):
        return obj.total_cost_price or Decimal('0')

    def get_expected_profit(self, obj):
        return obj.expected_profit or Decimal('0')


class SaleSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    customer_national_id = serializers.SerializerMethodField()
    car_vin = serializers.SerializerMethodField()
    car_brand = serializers.SerializerMethodField()
    car_model_name = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    actual_profit = serializers.SerializerMethodField()
    installments = SaleInstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = Sale
        fields = [
            'id',
            'car',
            'customer',
            'sales_employee',
            'sale_price',
            'amount_paid',
            'remaining_amount',
            'debt_due_date',
            'sale_date',
            'actual_profit',
            'car_vin',
            'car_brand',
            'car_model_name',
            'customer_name',
            'customer_national_id',
            'currency',
            'installments',
        ]

    def get_customer_name(self, obj):
        return getattr(obj.customer, 'name', '')

    def get_customer_national_id(self, obj):
        return getattr(obj.customer, 'national_id', '')

    def get_car_vin(self, obj):
        return getattr(obj.car, 'vin', '')

    def get_car_brand(self, obj):
        return getattr(obj.car, 'brand', '')

    def get_car_model_name(self, obj):
        return getattr(obj.car, 'model_name', '')

    def get_currency(self, obj):
        return getattr(obj.car, 'currency', 'SR')

    def get_remaining_amount(self, obj):
        return obj.remaining_amount

    def get_actual_profit(self, obj):
        return obj.actual_profit


class SaleProcessSerializer(serializers.Serializer):
    car_id = serializers.IntegerField()
    customer_name = serializers.CharField(max_length=100)
    customer_phone = serializers.CharField(max_length=20)
    customer_national_id = serializers.CharField(max_length=20)
    sale_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    debt_due_date = serializers.DateField(required=False, allow_null=True)
    payment_schedule = serializers.JSONField(required=False, default=list)
    sale_contract_image = serializers.ImageField(required=False, allow_null=True)
    currency_rate = serializers.DecimalField(required=False, max_digits=18, decimal_places=6, default=Decimal('1'))
    financial_container_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_customer_name(self, value):
        cleaned = sanitize_plain_text(value, max_length=100)
        if not cleaned:
            raise serializers.ValidationError('اسم العميل مطلوب.')
        return cleaned

    def validate_customer_phone(self, value):
        cleaned = sanitize_plain_text(value, max_length=20)
        if not PHONE_RE.match(cleaned):
            raise serializers.ValidationError('رقم الهاتف يحتوي على صيغة غير صالحة.')
        return cleaned

    def validate_customer_national_id(self, value):
        cleaned = sanitize_plain_text(value, max_length=20)
        if not cleaned:
            raise serializers.ValidationError('رقم الهوية مطلوب.')
        return cleaned


class FinancialConsistencyTaskSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    report_path = serializers.CharField(required=False, allow_blank=True, max_length=260)


class TenantBackupTaskSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(max_length=50)
    actor = serializers.CharField(required=False, allow_blank=True, max_length=150)


class DBIsolationTaskSerializer(serializers.Serializer):
    cleanup = serializers.BooleanField(required=False, default=False)
    force = serializers.BooleanField(required=False, default=False)
    skip_backup = serializers.BooleanField(required=False, default=False)
    report_path = serializers.CharField(required=False, allow_blank=True, max_length=260)


class TenantSnapshotTaskSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(max_length=50)


class FinanceVoucherSerializer(TenantBoundModelSerializer):
    def validate_person_name(self, value):
        cleaned = sanitize_plain_text(value, max_length=150)
        if not cleaned:
            raise serializers.ValidationError('الاسم مطلوب.')
        return cleaned

    def validate_reason(self, value):
        return sanitize_plain_text(value, max_length=255)

    class Meta:
        model = FinanceVoucher
        fields = [
            'id',
            'voucher_type',
            'voucher_number',
            'voucher_date',
            'person_name',
            'amount',
            'currency',
            'reason',
            'linked_car',
            'financial_container',
            'supporting_document',
            'debit_account',
            'credit_account',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class DebtPaymentSerializer(serializers.ModelSerializer):
    car_vin = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = DebtPayment
        fields = [
            'id',
            'sale',
            'receipt_number',
            'payment_date',
            'paid_amount',
            'created_at',
            'car_vin',
            'customer_name',
        ]
        read_only_fields = ['id', 'created_at', 'car_vin', 'customer_name']

    def get_car_vin(self, obj):
        return getattr(getattr(obj.sale, 'car', None), 'vin', '')

    def get_customer_name(self, obj):
        return getattr(getattr(obj.sale, 'customer', None), 'name', '')

    def validate_receipt_number(self, value):
        cleaned = sanitize_plain_text(value, max_length=30)
        if not cleaned:
            raise serializers.ValidationError('رقم السند مطلوب.')
        return cleaned


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'username',
            'tenant_id',
            'action',
            'target_model',
            'target_pk',
            'before_data',
            'after_data',
            'ip_address',
            'device_type',
            'browser',
            'geo_location',
            'request_path',
            'timestamp',
        ]

    def get_username(self, obj):
        return getattr(obj.user, 'username', '')
