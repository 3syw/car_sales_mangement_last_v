import json

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join
from .car_catalog import CAR_BRAND_MODELS
from .models import (
    AccountLedger,
    Car,
    CarEvaluation,
    CarHistory,
    CarLocation,
    CarReservation,
    Customer,
    CustomerAccount,
    Currency,
    Sale,
    SalesCommission,
    SaleInstallment,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    TaxRate,
    ExchangeRate,
    Invoice,
    InvoiceLine,
    InventoryTransaction,
    Employee,
    EmployeeRole,
    EmployeeCommission,
    Expense,
    GeneralExpense,
    CarDocument,
    AuditLog,
    InterfaceAccess,
    PlatformTenant,
    GlobalAuditLog,
    TenantBackupRecord,
    TenantMigrationRecord,
    CarMaintenance,
    DailyClosing,
    FinancialAccount,
    FinancialContainer,
    JournalEntry,
    JournalEntryLine,
    FiscalPeriodClosing,
    FiscalUnlockRequest,
)
from .quota import enforce_user_quota_or_raise, enforce_car_quota_or_raise, enforce_storage_quota_or_raise
from .tenant_context import get_current_tenant_db_alias


User = get_user_model()

ACCESS_FIELD_NAMES = (
    'can_access_dashboard',
    'can_access_cars',
    'can_access_reports',
    'can_access_debts',
    'can_access_timeline',
    'can_access_system_users',
    'can_add_maintenance_expenses',
)


class DatalistTextInput(forms.TextInput):
    def __init__(self, *args, datalist_id, options=None, use_native_datalist=True, **kwargs):
        attrs = kwargs.setdefault('attrs', {})
        self.use_native_datalist = use_native_datalist
        if self.use_native_datalist:
            attrs.setdefault('list', datalist_id)
        else:
            attrs.pop('list', None)
        self.datalist_id = datalist_id
        self.options = options or []
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        input_html = super().render(name, value, attrs=attrs, renderer=renderer)
        options_html = format_html_join(
            '',
            '<option value="{}"></option>',
            ((option,) for option in self.options),
        )
        return format_html('{}<datalist id="{}">{}</datalist>', input_html, self.datalist_id, options_html)


class UserAdminAddForm(UserCreationForm):
    can_access_dashboard = forms.BooleanField(label='الوصول إلى لوحة التحكم', required=False, initial=True)
    can_access_cars = forms.BooleanField(label='الوصول إلى المعرض', required=False, initial=True)
    can_access_reports = forms.BooleanField(label='الوصول إلى التقارير', required=False, initial=True)
    can_access_debts = forms.BooleanField(label='الوصول إلى الديون', required=False, initial=True)
    can_access_timeline = forms.BooleanField(label='الوصول إلى الجدول الزمني', required=False, initial=True)
    can_access_system_users = forms.BooleanField(label='الوصول إلى حسابات المستخدمين', required=False, initial=True)
    can_add_maintenance_expenses = forms.BooleanField(label='إضافة مصروفات صيانة', required=False, initial=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'username', 'is_active', 'password1', 'password2')

    def clean(self):
        cleaned_data = super().clean()
        enforce_user_quota_or_raise(extra_users=1)
        return cleaned_data


class UserAdminEditForm(UserChangeForm):
    can_access_dashboard = forms.BooleanField(label='الوصول إلى لوحة التحكم', required=False)
    can_access_cars = forms.BooleanField(label='الوصول إلى المعرض', required=False)
    can_access_reports = forms.BooleanField(label='الوصول إلى التقارير', required=False)
    can_access_debts = forms.BooleanField(label='الوصول إلى الديون', required=False)
    can_access_timeline = forms.BooleanField(label='الوصول إلى الجدول الزمني', required=False)
    can_access_system_users = forms.BooleanField(label='الوصول إلى حسابات المستخدمين', required=False)
    can_add_maintenance_expenses = forms.BooleanField(label='إضافة مصروفات صيانة', required=False)

    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if not instance:
            return

        tenant_alias = (get_current_tenant_db_alias() or '').strip()
        if not tenant_alias.startswith('tenant_'):
            for field_name in ACCESS_FIELD_NAMES:
                field = self.fields[field_name]
                field.disabled = True
                if field_name == 'can_add_maintenance_expenses':
                    field.initial = False
                else:
                    field.initial = True
                field.help_text = 'يتم تعديل هذه الصلاحيات داخل بيئة معرض مفعلة فقط.'
            return

        access, _ = InterfaceAccess.objects.using(tenant_alias).get_or_create(user_id=instance.pk)
        self.fields['can_access_dashboard'].initial = access.can_access_dashboard
        self.fields['can_access_cars'].initial = access.can_access_cars
        self.fields['can_access_reports'].initial = access.can_access_reports
        self.fields['can_access_debts'].initial = access.can_access_debts
        self.fields['can_access_timeline'].initial = access.can_access_timeline
        self.fields['can_access_system_users'].initial = access.can_access_system_users
        self.fields['can_add_maintenance_expenses'].initial = access.can_add_maintenance_expenses


class CustomUserAdmin(UserAdmin):
    add_form = UserAdminAddForm
    form = UserAdminEditForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'username', 'password1', 'password2'),
        }),
        ('الحالة', {
            'fields': ('is_active',),
        }),
        ('خيارات الوصول إلى الصفحات', {
            'fields': (
                'can_access_dashboard',
                'can_access_cars',
                'can_access_reports',
                'can_access_debts',
                'can_access_timeline',
                'can_access_system_users',
                'can_add_maintenance_expenses',
            ),
        }),
    )
    fieldsets = UserAdmin.fieldsets + (
        ('خيارات الوصول إلى الصفحات', {
            'fields': (
                'can_access_dashboard',
                'can_access_cars',
                'can_access_reports',
                'can_access_debts',
                'can_access_timeline',
                'can_access_system_users',
                'can_add_maintenance_expenses',
            ),
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        tenant_alias = (get_current_tenant_db_alias() or '').strip()
        if not tenant_alias.startswith('tenant_'):
            return

        access_defaults = {
            'can_access_dashboard': form.cleaned_data.get('can_access_dashboard', True),
            'can_access_cars': form.cleaned_data.get('can_access_cars', True),
            'can_access_reports': form.cleaned_data.get('can_access_reports', True),
            'can_access_debts': form.cleaned_data.get('can_access_debts', True),
            'can_access_timeline': form.cleaned_data.get('can_access_timeline', True),
            'can_access_system_users': form.cleaned_data.get('can_access_system_users', True),
            'can_add_maintenance_expenses': form.cleaned_data.get('can_add_maintenance_expenses', False),
        }
        InterfaceAccess.objects.using(tenant_alias).update_or_create(user_id=obj.pk, defaults=access_defaults)


class CarAdminForm(forms.ModelForm):
    cost_currency = forms.ChoiceField(
        label='عملة سعر التكلفة',
        choices=Car.CURRENCY_CHOICES,
        required=True,
    )

    year = forms.TypedChoiceField(
        choices=[(year, year) for year in range(1980, 2051)],
        coerce=int,
        label='سنة الصنع',
    )

    class Meta:
        model = Car
        fields = '__all__'

    class Media:
        js = ('sales/js/car_brand_model_admin.js',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        brand_options = sorted(CAR_BRAND_MODELS.keys())
        selected_brand = ''
        if self.is_bound:
            selected_brand = (self.data.get(self.add_prefix('brand')) or '').strip()
        elif self.instance and self.instance.pk:
            selected_brand = (self.instance.brand or '').strip()

        model_options = []
        if selected_brand:
            model_options = CAR_BRAND_MODELS.get(selected_brand, [])
            if not model_options:
                for brand_name, models in CAR_BRAND_MODELS.items():
                    if brand_name.lower() == selected_brand.lower():
                        model_options = models
                        break

        self.fields['brand'].widget = DatalistTextInput(
            datalist_id='car-brand-options',
            options=brand_options,
            use_native_datalist=False,
            attrs={
                'placeholder': 'اختر الماركة من القائمة أو اكتبها يدويًا',
                'autocomplete': 'new-password',
            },
        )
        self.fields['brand'].widget.attrs['data-brand-model-map'] = json.dumps(CAR_BRAND_MODELS, ensure_ascii=False)

        self.fields['model_name'].widget = DatalistTextInput(
            datalist_id='car-model-options',
            options=model_options,
            use_native_datalist=False,
            attrs={
                'placeholder': 'اختر الموديل من القائمة أو اكتب الموديل يدويًا',
                'autocomplete': 'new-password',
            },
        )
        selected_currency = ''
        if self.is_bound:
            selected_currency = (
                self.data.get(self.add_prefix('cost_currency'))
                or self.data.get(self.add_prefix('currency'))
                or ''
            )
        elif self.instance and self.instance.pk:
            selected_currency = self.instance.currency
        else:
            selected_currency = self.fields['currency'].initial or 'SR'

        self.fields['cost_currency'].initial = selected_currency
        self.fields['cost_currency'].widget.attrs.update({'class': 'vSelectMedium'})

        self.fields['brand'].help_text = 'يمكنك الاختيار من القائمة أو كتابة الماركة يدويًا.'
        self.fields['model_name'].help_text = 'تعتمد القائمة على الماركة المختارة، ويمكنك الكتابة يدويًا.'

    def clean_cost_currency(self):
        return self.cleaned_data.get('cost_currency') or 'SR'

    def clean_year(self):
        year = self.cleaned_data.get('year')
        if year is not None and (year < 1980 or year > 2050):
            raise ValidationError('سنة التصنيع يجب أن تكون بين 1980 و2050.')
        return year

    def clean(self):
        cleaned_data = super().clean()

        chosen_currency = cleaned_data.get('cost_currency') or cleaned_data.get('currency') or 'SR'
        cleaned_data['currency'] = chosen_currency
        cleaned_data['cost_currency'] = chosen_currency

        if not self.instance.pk:
            enforce_car_quota_or_raise(extra_cars=1)

        additional_bytes = 0
        image_file = cleaned_data.get('image')
        contract_file = cleaned_data.get('contract_image')

        if image_file is not None and hasattr(image_file, 'size'):
            additional_bytes += int(image_file.size)
        if contract_file is not None and hasattr(contract_file, 'size'):
            additional_bytes += int(contract_file.size)

        if additional_bytes:
            enforce_storage_quota_or_raise(additional_bytes=additional_bytes)

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.currency = self.cleaned_data.get('currency') or self.cleaned_data.get('cost_currency') or instance.currency

        if commit:
            instance.save()
            self.save_m2m()

        return instance

# هذه الطريقة تجعل لوحة التحكم منظمة واحترافية
@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    form = CarAdminForm
    change_form_template = 'admin/sales/car/change_form.html'

    # الأعمدة التي ستظهر في القائمة الرئيسية للسيارات
    list_display = ('brand', 'model_name', 'vin', 'selling_price', 'is_sold')
    
    # إضافة شريط بحث برقم الشاسيه أو الماركة
    search_fields = ('vin', 'brand', 'model_name')
    
    # إضافة فلتر جانبي لتصفية السيارات المباعة وغير المباعة
    list_filter = ('is_sold', 'brand', 'year')
    fields = (
        'brand',
        'model_name',
        'vin',
        'year',
        ('insurance_expiry', 'registration_expiry'),
        ('cost_price', 'cost_currency'),
        ('customs_cost', 'transport_cost', 'commission_cost'),
        ('selling_price', 'currency'),
        'image',
        'contract_image',
        'is_sold',
    )

    add_fieldsets = (
        ('البيانات التقنية', {
            'classes': ('car-add-tech',),
            'fields': ('brand', 'model_name', 'vin', 'year', ('insurance_expiry', 'registration_expiry')),
        }),
        ('البيانات المالية', {
            'classes': ('car-add-finance',),
            'fields': (
                ('cost_price', 'cost_currency'),
                ('customs_cost', 'transport_cost', 'commission_cost'),
                ('selling_price', 'currency'),
            ),
        }),
        ('الصور والمستندات', {
            'classes': ('car-add-uploads',),
            'fields': ('image', 'contract_image'),
        }),
        ('الحالة', {
            'classes': ('car-add-status',),
            'fields': ('is_sold',),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

admin.site.register(Customer)


@admin.register(PlatformTenant)
class PlatformTenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant_id', 'is_active', 'is_deleted', 'deleted_at', 'max_cars', 'max_users', 'max_storage_mb', 'created_at')
    search_fields = ('name', 'tenant_id')
    list_filter = ('is_active', 'is_deleted')


@admin.register(GlobalAuditLog)
class GlobalAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'event_type', 'tenant_id', 'actor_username', 'data_size_bytes')
    search_fields = ('tenant_id', 'actor_username', 'notes')
    list_filter = ('event_type', 'created_at')


@admin.register(TenantBackupRecord)
class TenantBackupRecordAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'file_size_bytes', 'created_by')
    search_fields = ('tenant__tenant_id', 'created_by', 'backup_file')


@admin.register(TenantMigrationRecord)
class TenantMigrationRecordAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'status', 'duration_ms')
    search_fields = ('tenant__tenant_id', 'details')
    list_filter = ('status', 'created_at')


@admin.register(DailyClosing)
class DailyClosingAdmin(admin.ModelAdmin):
    list_display = ('closing_date', 'closed_by', 'created_at')
    search_fields = ('notes', 'closed_by__username')
    list_filter = ('closing_date',)


@admin.register(FinancialAccount)
class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_system', 'is_active')
    list_filter = ('account_type', 'is_system', 'is_active')
    search_fields = ('code', 'name', 'notes')


@admin.register(FinancialContainer)
class FinancialContainerAdmin(admin.ModelAdmin):
    list_display = ('name', 'container_type', 'currency', 'linked_account', 'opening_balance', 'is_active')
    list_filter = ('container_type', 'currency', 'is_active')
    search_fields = ('name', 'notes', 'linked_account__code', 'linked_account__name')


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 0
    readonly_fields = ('account', 'line_description', 'debit', 'credit', 'currency', 'container', 'car')
    can_delete = False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('entry_number', 'entry_date', 'description', 'source_model', 'source_reference', 'created_by')
    search_fields = ('entry_number', 'description', 'source_model', 'source_reference')
    list_filter = ('entry_date', 'source_model')
    readonly_fields = ('entry_number', 'entry_date', 'description', 'source_model', 'source_pk', 'source_reference', 'created_by', 'created_at')
    inlines = [JournalEntryLineInline]

    def has_add_permission(self, request):
        return False


@admin.register(FiscalPeriodClosing)
class FiscalPeriodClosingAdmin(admin.ModelAdmin):
    list_display = ('period_type', 'period_start', 'period_end', 'is_locked', 'closed_by', 'created_at')
    list_filter = ('period_type', 'is_locked', 'period_start', 'period_end')
    search_fields = ('notes', 'closed_by__username')


@admin.register(FiscalUnlockRequest)
class FiscalUnlockRequestAdmin(admin.ModelAdmin):
    list_display = ('closing', 'status', 'requested_by', 'reviewed_by', 'created_at', 'reviewed_at')
    list_filter = ('status', 'created_at', 'reviewed_at')
    search_fields = ('reason', 'review_notes', 'requested_by__username', 'reviewed_by__username')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'car', 'expense_type', 'amount', 'date')
    list_filter = ('expense_type', 'date')
    search_fields = ('title', 'notes', 'car__brand', 'car__vin')


@admin.register(CarMaintenance)
class CarMaintenanceAdmin(admin.ModelAdmin):
    list_display = ('car', 'amount', 'maintenance_type', 'operation_date', 'supplier_workshop', 'payment_method', 'added_by')
    list_filter = ('maintenance_type', 'payment_method', 'operation_date')
    search_fields = ('car__brand', 'car__vin', 'supplier_workshop')


@admin.register(CarDocument)
class CarDocumentAdmin(admin.ModelAdmin):
    list_display = ('car', 'document_type', 'upload_date', 'uploaded_by')
    list_filter = ('document_type', 'upload_date')
    search_fields = ('car__brand', 'car__vin')


@admin.register(GeneralExpense)
class GeneralExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'amount', 'currency', 'expense_date', 'created_by')
    list_filter = ('category', 'currency', 'expense_date')
    search_fields = ('title', 'description')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'target_model', 'target_pk', 'user', 'tenant_id', 'ip_address', 'device_type', 'browser', 'geo_location')
    list_filter = ('action', 'target_model', 'timestamp')
    search_fields = ('target_pk', 'tenant_id', 'ip_address', 'request_path')
    readonly_fields = (
        'id',
        'timestamp',
        'user',
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
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('car', 'customer', 'sale_price', 'amount_paid', 'sale_date')
    fields = ('car', 'customer', 'sale_price', 'amount_paid', 'debt_due_date', 'sale_contract_image')

    # تقييد القائمة لتظهر السيارات المتاحة فقط
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "car":
            kwargs["queryset"] = Car.objects.filter(is_sold=False)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(SaleInstallment)
class SaleInstallmentAdmin(admin.ModelAdmin):
    list_display = ('sale', 'installment_order', 'due_date', 'amount', 'paid_amount', 'status')
    list_filter = ('status', 'due_date')
    search_fields = ('sale__car__vin', 'sale__customer__name')


@admin.register(AccountLedger)
class AccountLedgerAdmin(admin.ModelAdmin):
    list_display = ('transaction_date', 'account', 'debit', 'credit', 'balance_after', 'reference_type', 'reference_id')
    list_filter = ('transaction_date', 'reference_type')
    search_fields = ('account__code', 'account__name', 'reference_id', 'notes')
    readonly_fields = (
        'account',
        'journal_line',
        'transaction_date',
        'debit',
        'credit',
        'balance_after',
        'reference_type',
        'reference_id',
        'notes',
        'created_at',
    )

    def has_add_permission(self, request):
        return False


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    list_display = ('customer', 'total_debt', 'total_paid', 'current_balance', 'last_payment_date', 'updated_at')
    search_fields = ('customer__name', 'customer__phone', 'customer__national_id')
    readonly_fields = ('customer', 'total_debt', 'total_paid', 'current_balance', 'last_payment_date', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'tax_number', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'phone', 'tax_number')


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'supplier', 'car', 'invoice_date', 'total_amount', 'paid_amount', 'status')
    list_filter = ('status', 'invoice_date')
    search_fields = ('invoice_number', 'supplier__name', 'car__vin')


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_number', 'supplier', 'invoice', 'payment_date', 'amount', 'payment_method')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('payment_number', 'supplier__name', 'invoice__invoice_number')


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ('car', 'transaction_type', 'transaction_date', 'cost', 'reference_type', 'reference_id')
    list_filter = ('transaction_type', 'transaction_date')
    search_fields = ('car__vin', 'reference_type', 'reference_id', 'notes')


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'customer', 'invoice_date', 'subtotal', 'tax_amount', 'total_amount', 'status')
    list_filter = ('status', 'invoice_date', 'currency')
    search_fields = ('invoice_number', 'customer__name')
    inlines = [InvoiceLineInline]


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ('name', 'rate_percent', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'symbol', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'symbol')


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('from_currency', 'to_currency', 'rate_date', 'rate')
    list_filter = ('rate_date',)
    search_fields = ('from_currency__code', 'to_currency__code')


@admin.register(EmployeeRole)
class EmployeeRoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'role', 'user', 'phone', 'hire_date', 'is_active')
    list_filter = ('is_active', 'role')
    search_fields = ('full_name', 'phone', 'user__username')


@admin.register(EmployeeCommission)
class EmployeeCommissionAdmin(admin.ModelAdmin):
    list_display = ('employee', 'period_start', 'period_end', 'amount', 'is_paid', 'paid_at')
    list_filter = ('is_paid', 'period_start')
    search_fields = ('employee__full_name',)


@admin.register(SalesCommission)
class SalesCommissionAdmin(admin.ModelAdmin):
    list_display = ('sale', 'employee', 'commission_rate', 'commission_amount', 'payout_status', 'paid_at')
    list_filter = ('payout_status',)
    search_fields = ('sale__car__vin', 'employee__full_name')


@admin.register(CarHistory)
class CarHistoryAdmin(admin.ModelAdmin):
    list_display = ('car', 'event_type', 'event_date', 'reference_type', 'reference_id')
    list_filter = ('event_type', 'event_date')
    search_fields = ('car__vin', 'reference_type', 'reference_id', 'notes')


@admin.register(CarReservation)
class CarReservationAdmin(admin.ModelAdmin):
    list_display = ('car', 'customer', 'reservation_date', 'expiry_date', 'deposit_amount', 'is_active')
    list_filter = ('is_active', 'reservation_date', 'expiry_date')
    search_fields = ('car__vin', 'customer__name')


@admin.register(CarEvaluation)
class CarEvaluationAdmin(admin.ModelAdmin):
    list_display = ('car', 'evaluation_date', 'market_value', 'evaluator_name')
    list_filter = ('evaluation_date',)
    search_fields = ('car__vin', 'evaluator_name')


@admin.register(CarLocation)
class CarLocationAdmin(admin.ModelAdmin):
    list_display = ('car', 'showroom_name', 'row_label', 'spot_label', 'updated_at')
    list_filter = ('showroom_name', 'row_label')
    search_fields = ('car__vin', 'showroom_name', 'row_label', 'spot_label')


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, CustomUserAdmin)