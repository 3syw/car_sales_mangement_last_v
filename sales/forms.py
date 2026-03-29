import json
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from .car_catalog import CAR_BRAND_MODELS
from .models import (
    Car,
    Sale,
    Customer,
    DebtPayment,
    CarMaintenance,
    CarDocument,
    GeneralExpense,
    DailyClosing,
    FinancialAccount,
    FinancialContainer,
    FiscalPeriodClosing,
)
from .quota import enforce_car_quota_or_raise, enforce_storage_quota_or_raise


def _safe_upload_size(file_obj):
    if file_obj is None:
        return 0
    size = getattr(file_obj, 'size', None)
    if size is None:
        return 0
    try:
        return int(size)
    except Exception:
        return 0


class DatalistTextInput(forms.TextInput):
    def __init__(self, *args, datalist_id, options=None, **kwargs):
        attrs = kwargs.setdefault('attrs', {})
        attrs.setdefault('list', datalist_id)
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

class CarForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = [
            'brand',
            'model_name',
            'vin',
            'year',
            'insurance_expiry',
            'registration_expiry',
            'cost_price',
            'customs_cost',
            'transport_cost',
            'commission_cost',
            'selling_price',
            'currency',
            'image',
            'contract_image',
            'is_sold',
        ]
        widgets = {
            'brand': forms.TextInput(attrs={'class': 'form-control'}),
            'model_name': forms.TextInput(attrs={'class': 'form-control'}),
            'vin': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'insurance_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'registration_expiry': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'customs_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'transport_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'commission_cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'contract_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'is_sold': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

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
            attrs={
                'class': 'form-control',
                'placeholder': 'اختر الماركة من القائمة أو اكتبها يدويًا',
                'autocomplete': 'off',
            },
        )
        self.fields['brand'].widget.attrs['data-brand-model-map'] = json.dumps(CAR_BRAND_MODELS, ensure_ascii=False)

        self.fields['model_name'].widget = DatalistTextInput(
            datalist_id='car-model-options',
            options=model_options,
            attrs={
                'class': 'form-control',
                'placeholder': 'اختر الموديل من القائمة أو اكتب الموديل يدويًا',
                'autocomplete': 'off',
            },
        )

class SaleForm(forms.ModelForm):
    # إضافة حقول العميل مباشرة في نموذج البيع لتسهيل الأمر
    customer_name = forms.CharField(label="اسم المشتري", max_length=100)
    customer_phone = forms.CharField(label="رقم الهاتف", max_length=20)
    customer_national_id = forms.CharField(label="رقم الهوية", max_length=20)
    currency_rate = forms.DecimalField(
        label='سعر الصرف وقت العملية',
        required=False,
        initial=Decimal('1'),
        min_value=Decimal('0.000001'),
        max_digits=18,
        decimal_places=6,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001'}),
    )
    financial_container = forms.ModelChoiceField(
        label='الصندوق/البنك (اختياري)',
        queryset=FinancialContainer.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    payment_schedule = forms.CharField(
        label='جدول الأقساط (JSON اختياري)',
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': '[{"due_date":"2026-04-15","amount":10000},{"due_date":"2026-05-15","amount":15000}]',
            }
        ),
    )
    
    class Meta:
        model = Sale
        fields = ['sale_price', 'amount_paid', 'debt_due_date', 'sale_contract_image'] # سعر البيع الفعلي
        widgets = {
            'sale_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'debt_due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'sale_contract_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)

        containers_qs = FinancialContainer.objects.filter(is_active=True).order_by('name', 'id')
        if tenant_alias:
            containers_qs = containers_qs.using(tenant_alias)
        self.fields['financial_container'].queryset = containers_qs

    def clean(self):
        cleaned_data = super().clean()
        sale_price = cleaned_data.get('sale_price')
        amount_paid = cleaned_data.get('amount_paid')
        debt_due_date = cleaned_data.get('debt_due_date')
        sale_contract_image = cleaned_data.get('sale_contract_image')
        currency_rate = cleaned_data.get('currency_rate')
        payment_schedule_text = (cleaned_data.get('payment_schedule') or '').strip()

        if currency_rate is None:
            cleaned_data['currency_rate'] = Decimal('1')

        if payment_schedule_text:
            try:
                parsed_schedule = json.loads(payment_schedule_text)
            except Exception:
                self.add_error('payment_schedule', 'تنسيق جدول الأقساط غير صالح. الرجاء إدخال JSON صحيح.')
            else:
                if not isinstance(parsed_schedule, list):
                    self.add_error('payment_schedule', 'جدول الأقساط يجب أن يكون قائمة JSON.')
                else:
                    cleaned_data['payment_schedule'] = parsed_schedule
        else:
            cleaned_data['payment_schedule'] = []

        if sale_price is not None and amount_paid is not None and amount_paid > sale_price:
            self.add_error('amount_paid', 'المبلغ المدفوع لا يمكن أن يكون أكبر من سعر البيع النهائي.')

        if sale_price is not None and amount_paid is not None:
            if amount_paid < sale_price:
                if debt_due_date is None:
                    cleaned_data['debt_due_date'] = timezone.localdate() + timedelta(days=30)
                if not sale_contract_image:
                    self.add_error('sale_contract_image', 'يجب رفع عقد البيع الموقّع لإتمام البيع الآجل.')
            else:
                cleaned_data['debt_due_date'] = None

        upload_bytes = _safe_upload_size(sale_contract_image)
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)

        return cleaned_data


class DebtPaymentForm(forms.ModelForm):
    class Meta:
        model = DebtPayment
        fields = ['receipt_number', 'payment_date', 'paid_amount']
        widgets = {
            'receipt_number': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'paid_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class CarMaintenanceForm(forms.ModelForm):
    class Meta:
        model = CarMaintenance
        fields = ['amount', 'maintenance_type', 'operation_date', 'supplier_workshop', 'payment_method', 'invoice_image']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'maintenance_type': forms.Select(attrs={'class': 'form-select'}),
            'operation_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'supplier_workshop': forms.TextInput(attrs={'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'invoice_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        upload_bytes = _safe_upload_size(cleaned_data.get('invoice_image'))
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)
        return cleaned_data


class CarDocumentForm(forms.ModelForm):
    class Meta:
        model = CarDocument
        fields = ['document_type', 'file']
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        upload_bytes = _safe_upload_size(cleaned_data.get('file'))
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)
        return cleaned_data


class GeneralExpenseForm(forms.ModelForm):
    class Meta:
        model = GeneralExpense
        fields = ['title', 'category', 'amount', 'currency', 'expense_date', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'expense_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class FinancialAccountForm(forms.ModelForm):
    class Meta:
        model = FinancialAccount
        fields = ['code', 'name', 'account_type', 'parent', 'notes', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 5110'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_type': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        queryset = FinancialAccount.objects.filter(is_active=True).order_by('code')
        if tenant_alias:
            queryset = queryset.using(tenant_alias)
        self.fields['parent'].queryset = queryset


class FinancialContainerForm(forms.ModelForm):
    class Meta:
        model = FinancialContainer
        fields = ['name', 'container_type', 'currency', 'linked_account', 'opening_balance', 'is_active', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'container_type': forms.Select(attrs={'class': 'form-select'}),
            'currency': forms.Select(attrs={'class': 'form-select'}),
            'linked_account': forms.Select(attrs={'class': 'form-select'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        queryset = FinancialAccount.objects.filter(is_active=True).order_by('code')
        if tenant_alias:
            queryset = queryset.using(tenant_alias)
        self.fields['linked_account'].queryset = queryset


class FiscalPeriodClosingForm(forms.Form):
    reference_date = forms.DateField(
        label='تاريخ ضمن الشهر المراد إغلاقه',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    notes = forms.CharField(
        label='ملاحظات الإغلاق',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )


class FiscalUnlockRequestForm(forms.Form):
    closing = forms.ModelChoiceField(
        label='الفترة المغلقة',
        queryset=FiscalPeriodClosing.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    reason = forms.CharField(
        label='مبرر فك الإغلاق',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        queryset = FiscalPeriodClosing.objects.filter(is_locked=True).order_by('-period_end')
        if tenant_alias:
            queryset = queryset.using(tenant_alias)
        self.fields['closing'].queryset = queryset


class ReceiptVoucherForm(forms.Form):
    voucher_number = forms.CharField(
        label='رقم السند',
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    voucher_date = forms.DateField(
        label='التاريخ',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    receiver_name = forms.CharField(
        label='استلم الأخ :',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    receipt_amount = forms.DecimalField(
        label='مبلغ وقدره :',
        min_value=0.01,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    receipt_currency = forms.ChoiceField(
        label='العملة',
        choices=Car.CURRENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    receipt_reason = forms.CharField(
        label='وذلك مقابل :',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    financial_container = forms.ModelChoiceField(
        label='الوعاء المالي',
        queryset=FinancialContainer.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    linked_car = forms.ModelChoiceField(
        label='مركز التكلفة (اختياري)',
        queryset=Car.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    supporting_document = forms.FileField(
        label='مستند مرفق (اختياري)',
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        containers = FinancialContainer.objects.filter(is_active=True).order_by('name')
        cars = Car.objects.all().order_by('brand', 'model_name', 'vin')
        if tenant_alias:
            containers = containers.using(tenant_alias)
            cars = cars.using(tenant_alias)
        self.fields['financial_container'].queryset = containers
        self.fields['linked_car'].queryset = cars

    def clean(self):
        cleaned_data = super().clean()
        upload_bytes = _safe_upload_size(cleaned_data.get('supporting_document'))
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)
        return cleaned_data


class PaymentVoucherForm(forms.Form):
    voucher_number = forms.CharField(
        label='رقم السند',
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    voucher_date = forms.DateField(
        label='التاريخ',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    payer_name = forms.CharField(
        label='دفع الأخ :',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    payment_amount = forms.DecimalField(
        label='مبلغ وقدره :',
        min_value=0.01,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    payment_currency = forms.ChoiceField(
        label='العملة',
        choices=Car.CURRENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    payment_reason = forms.CharField(
        label='وذلك مقابل :',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    financial_container = forms.ModelChoiceField(
        label='الوعاء المالي',
        queryset=FinancialContainer.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    linked_car = forms.ModelChoiceField(
        label='مركز التكلفة (اختياري)',
        queryset=Car.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    supporting_document = forms.FileField(
        label='مستند مرفق (اختياري)',
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        containers = FinancialContainer.objects.filter(is_active=True).order_by('name')
        cars = Car.objects.all().order_by('brand', 'model_name', 'vin')
        if tenant_alias:
            containers = containers.using(tenant_alias)
            cars = cars.using(tenant_alias)
        self.fields['financial_container'].queryset = containers
        self.fields['linked_car'].queryset = cars

    def clean(self):
        cleaned_data = super().clean()
        upload_bytes = _safe_upload_size(cleaned_data.get('supporting_document'))
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)
        return cleaned_data


class OperatingExpenseVoucherForm(forms.Form):
    voucher_number = forms.CharField(
        label='رقم السند',
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    voucher_date = forms.DateField(
        label='التاريخ',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    expense_name = forms.CharField(
        label='الاسم :',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    expense_amount = forms.DecimalField(
        label='مبلغ وقدره :',
        min_value=0.01,
        decimal_places=2,
        max_digits=12,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
    expense_currency = forms.ChoiceField(
        label='العملة',
        choices=Car.CURRENCY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    allowance_reason = forms.CharField(
        label='بدل :',
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm'})
    )
    financial_container = forms.ModelChoiceField(
        label='الوعاء المالي',
        queryset=FinancialContainer.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    linked_car = forms.ModelChoiceField(
        label='مركز التكلفة (اختياري)',
        queryset=Car.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    supporting_document = forms.FileField(
        label='صورة الفاتورة/المستند',
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, tenant_alias='', **kwargs):
        super().__init__(*args, **kwargs)
        containers = FinancialContainer.objects.filter(is_active=True).order_by('name')
        cars = Car.objects.all().order_by('brand', 'model_name', 'vin')
        if tenant_alias:
            containers = containers.using(tenant_alias)
            cars = cars.using(tenant_alias)
        self.fields['financial_container'].queryset = containers
        self.fields['linked_car'].queryset = cars

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('supporting_document'):
            self.add_error('supporting_document', 'رفع المستند إلزامي لسند المصروف التشغيلي.')
        upload_bytes = _safe_upload_size(cleaned_data.get('supporting_document'))
        if upload_bytes:
            enforce_storage_quota_or_raise(additional_bytes=upload_bytes)
        return cleaned_data


class TenantLoginForm(forms.Form):
    tenant_id = forms.CharField(
        label='معرف المعرض',
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: showroom-alfa'})
    )
    tenant_key = forms.CharField(
        label='كلمة مرور المعرض',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    username = forms.CharField(
        label='اسم المستخدم',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='كلمة مرور الحساب',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class TenantRegisterForm(UserCreationForm):
    showroom_name = forms.CharField(
        label='اسم المعرض',
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    tenant_id = forms.SlugField(
        label='معرف المعرض (ID)',
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: showroom-alfa'})
    )
    tenant_key = forms.CharField(
        label='كلمة مرور المعرض',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('showroom_name', 'tenant_id', 'tenant_key', 'username', 'password1', 'password2')


class PlatformOwnerLoginForm(forms.Form):
    username = forms.CharField(
        label='اسم مستخدم المنصة',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    password = forms.CharField(
        label='كلمة مرور المنصة',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )


class TenantSwitchForm(forms.Form):
    tenant_id = forms.SlugField(
        label='معرف المعرض الهدف',
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: showroom-alfa'})
    )


class DailyClosingForm(forms.ModelForm):
    class Meta:
        model = DailyClosing
        fields = ['closing_date', 'notes']
        widgets = {
            'closing_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ملاحظة اختيارية عن الإغلاق'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['closing_date'].initial = timezone.localdate()


class BankReconciliationUploadForm(forms.Form):
    statement_file = forms.FileField(
        label='ملف كشف الحساب البنكي (Excel)',
        help_text='يجب أن يحتوي الملف على أعمدة: رقم السند، التاريخ، المبلغ، العملة (اختياري).',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xlsx,.xlsm'}),
    )
    start_date = forms.DateField(
        required=False,
        label='من تاريخ',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    end_date = forms.DateField(
        required=False,
        label='إلى تاريخ',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def clean_statement_file(self):
        file_obj = self.cleaned_data['statement_file']
        file_name = (file_obj.name or '').lower()
        if not (file_name.endswith('.xlsx') or file_name.endswith('.xlsm')):
            raise forms.ValidationError('الملف يجب أن يكون بصيغة Excel حديثة (.xlsx أو .xlsm).')
        return file_obj

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية.')
        return cleaned_data


