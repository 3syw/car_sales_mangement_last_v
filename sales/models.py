#السيارات
import uuid

from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal


class PlatformTenant(models.Model):
    name = models.CharField('اسم المعرض', max_length=120)
    tenant_id = models.SlugField('معرف المعرض', max_length=50, unique=True)
    access_key_hash = models.CharField('تجزئة كلمة مرور المعرض', max_length=128)
    is_active = models.BooleanField('نشط', default=True)
    max_cars = models.PositiveIntegerField('الحد الأقصى للسيارات', default=500)
    max_users = models.PositiveIntegerField('الحد الأقصى للمستخدمين', default=25)
    max_storage_mb = models.PositiveIntegerField('الحد الأقصى للمساحة (MB)', default=2048)
    is_deleted = models.BooleanField('محذوف ناعمًا', default=False)
    deleted_at = models.DateTimeField('تاريخ الحذف', null=True, blank=True)
    deleted_by = models.CharField('تم الحذف بواسطة', max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'معرض'
        verbose_name_plural = 'المعارض'

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"

    def set_access_key(self, raw_key):
        self.access_key_hash = make_password(raw_key)

    def check_access_key(self, raw_key):
        return check_password(raw_key, self.access_key_hash)

    def soft_delete(self, actor_username=''):
        from django.utils import timezone

        self.is_active = False
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = (actor_username or '')[:150]

    def restore_soft_deleted(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = ''


class GlobalAuditLog(models.Model):
    EVENT_CHOICES = [
        ('tenant_login', 'دخول معرض'),
        ('tenant_logout', 'خروج معرض'),
        ('platform_login', 'دخول منصة فوقية'),
        ('platform_switch', 'تحويل معرض فني'),
        ('platform_exit_switch', 'إنهاء التحويل الفني'),
        ('fiscal_period_close', 'إغلاق فترة مالية'),
        ('fiscal_unlock_request', 'طلب فك إغلاق مالي'),
        ('fiscal_unlock_approved', 'اعتماد فك الإغلاق المالي'),
        ('fiscal_unlock_rejected', 'رفض فك الإغلاق المالي'),
        ('tenant_backup', 'نسخة احتياطية معرض'),
        ('tenant_restore', 'استعادة معرض'),
        ('tenant_soft_delete', 'حذف ناعم لمعرض'),
        ('tenant_restore_soft_deleted', 'إعادة تفعيل معرض محذوف ناعمًا'),
        ('tenant_migrate', 'هجرة معرض'),
    ]

    tenant_id = models.SlugField('معرف المعرض', max_length=50, blank=True)
    actor_username = models.CharField('اسم الحساب المنفذ', max_length=150, blank=True)
    event_type = models.CharField('نوع الحدث', max_length=40, choices=EVENT_CHOICES)
    data_size_bytes = models.BigIntegerField('حجم البيانات بالبايت', default=0)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField('وقت الحدث', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سجل منصة عام'
        verbose_name_plural = 'سجل المنصة العام'

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.tenant_id or 'عام'}"


class TenantBackupRecord(models.Model):
    tenant = models.ForeignKey(PlatformTenant, on_delete=models.CASCADE, related_name='backup_records', verbose_name='المعرض')
    backup_file = models.CharField('مسار ملف النسخة', max_length=260)
    file_size_bytes = models.BigIntegerField('حجم الملف', default=0)
    created_by = models.CharField('المنفذ', max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'نسخة احتياطية معرض'
        verbose_name_plural = 'النسخ الاحتياطية للمعارض'

    def __str__(self):
        return f"{self.tenant.tenant_id} - {self.backup_file}"


class TenantMigrationRecord(models.Model):
    STATUS_CHOICES = [
        ('success', 'نجاح'),
        ('failed', 'فشل'),
    ]

    tenant = models.ForeignKey(PlatformTenant, on_delete=models.CASCADE, related_name='migration_records', verbose_name='المعرض')
    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES)
    duration_ms = models.PositiveIntegerField('المدة بالميلي ثانية', default=0)
    details = models.CharField('تفاصيل', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سجل هجرة معرض'
        verbose_name_plural = 'سجلات هجرة المعارض'

    def __str__(self):
        return f"{self.tenant.tenant_id} - {self.status}"


class DailyClosing(models.Model):
    closing_date = models.DateField('تاريخ اليومية المغلقة', unique=True)
    closed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='daily_closings',
        verbose_name='تم الإغلاق بواسطة',
    )
    notes = models.CharField('ملاحظات الإغلاق', max_length=255, blank=True)
    created_at = models.DateTimeField('وقت الإغلاق', auto_now_add=True)

    class Meta:
        ordering = ['-closing_date', '-created_at']
        verbose_name = 'إغلاق يومية'
        verbose_name_plural = 'إغلاقات اليومية'

    def __str__(self):
        return f"إغلاق يومية {self.closing_date}"


class FinancialAccount(models.Model):
    ACCOUNT_TYPE_ASSET = 'asset'
    ACCOUNT_TYPE_LIABILITY = 'liability'
    ACCOUNT_TYPE_EQUITY = 'equity'
    ACCOUNT_TYPE_REVENUE = 'revenue'
    ACCOUNT_TYPE_EXPENSE = 'expense'

    ACCOUNT_TYPE_CHOICES = [
        (ACCOUNT_TYPE_ASSET, 'أصول'),
        (ACCOUNT_TYPE_LIABILITY, 'خصوم'),
        (ACCOUNT_TYPE_EQUITY, 'حقوق ملكية'),
        (ACCOUNT_TYPE_REVENUE, 'إيرادات'),
        (ACCOUNT_TYPE_EXPENSE, 'مصروفات'),
    ]

    code = models.CharField('رمز الحساب', max_length=20, unique=True)
    name = models.CharField('اسم الحساب', max_length=160)
    account_type = models.CharField('نوع الحساب', max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='الحساب الأب',
    )
    is_active = models.BooleanField('نشط', default=True)
    is_system = models.BooleanField('حساب نظام', default=False)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code', 'id']
        verbose_name = 'حساب مالي'
        verbose_name_plural = 'شجرة الحسابات'

    def __str__(self):
        return f"{self.code} - {self.name}"


class FiscalPeriodClosing(models.Model):
    PERIOD_MONTHLY = 'monthly'
    PERIOD_TYPE_CHOICES = [
        (PERIOD_MONTHLY, 'إغلاق شهري'),
    ]

    period_type = models.CharField('نوع الإغلاق', max_length=20, choices=PERIOD_TYPE_CHOICES, default=PERIOD_MONTHLY)
    period_start = models.DateField('بداية الفترة')
    period_end = models.DateField('نهاية الفترة')
    is_locked = models.BooleanField('الفترة مغلقة', default=True)
    closed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fiscal_period_closings',
        verbose_name='تم الإغلاق بواسطة',
    )
    notes = models.CharField('ملاحظات الإغلاق', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_end', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['period_type', 'period_start', 'period_end'],
                name='uniq_fiscal_period_closing_window',
            )
        ]
        verbose_name = 'إغلاق فترة مالية'
        verbose_name_plural = 'إغلاقات الفترات المالية'

    def __str__(self):
        return f"{self.get_period_type_display()} ({self.period_start} - {self.period_end})"


class FiscalUnlockRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'قيد المراجعة'),
        (STATUS_APPROVED, 'مقبول'),
        (STATUS_REJECTED, 'مرفوض'),
    ]

    closing = models.ForeignKey(
        FiscalPeriodClosing,
        on_delete=models.CASCADE,
        related_name='unlock_requests',
        verbose_name='الفترة المالية',
    )
    requested_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fiscal_unlock_requests',
        verbose_name='طالب فك الإغلاق',
    )
    reason = models.TextField('مبرر طلب فك الإغلاق')
    status = models.CharField('الحالة', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fiscal_unlock_reviews',
        verbose_name='تمت المراجعة بواسطة',
    )
    review_notes = models.CharField('ملاحظات المراجعة', max_length=255, blank=True)
    reviewed_at = models.DateTimeField('تاريخ المراجعة', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'طلب فك إغلاق'
        verbose_name_plural = 'طلبات فك الإغلاق'

    def __str__(self):
        return f"{self.closing} - {self.get_status_display()}"

class Car(models.Model):
# الخيارات المتاحة للعملات (العلامة الرقمية هي المخزنة)
    CURRENCY_CHOICES = [
        ('$', 'دولار ($)'),
        ('SR', 'ريال سعودي (SR)'),
        ('£', 'جنيه إسترليني (£)'),
    ]

    brand = models.CharField("الماركة", max_length=50)
    model_name = models.CharField("الموديل", max_length=50)
    vin = models.CharField("رقم الشاسيه", max_length=17, unique=True)
    year = models.PositiveIntegerField("سنة الصنع")
    cost_price = models.DecimalField("سعر التكلفة", max_digits=12, decimal_places=2)
    customs_cost = models.DecimalField('رسوم الجمارك', max_digits=12, decimal_places=2, default=Decimal('0'))
    transport_cost = models.DecimalField('تكاليف النقل', max_digits=12, decimal_places=2, default=Decimal('0'))
    commission_cost = models.DecimalField('العمولة', max_digits=12, decimal_places=2, default=Decimal('0'))
    selling_price = models.DecimalField("سعر البيع", max_digits=12, decimal_places=2)
    image = models.ImageField("صورة السيارة", upload_to='cars/', null=True, blank=True)
    contract_image = models.ImageField("صورة العقد/الأوراق", upload_to='car_docs/', null=True, blank=True)
    insurance_expiry = models.DateField('تاريخ انتهاء التأمين', null=True, blank=True)
    registration_expiry = models.DateField('تاريخ انتهاء الاستمارة', null=True, blank=True)
    
    # الحقل الجديد لاختيار العملة
    currency = models.CharField("العملة", max_length=3, choices=CURRENCY_CHOICES, default='SR')
    
    is_sold = models.BooleanField("تم البيع؟", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.brand} - {self.vin}"

    @property
    def maintenance_total(self):
        total = self.maintenance_records.aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        return total

    @property
    def additional_costs_total(self):
        return (
            (self.customs_cost or Decimal('0'))
            + (self.transport_cost or Decimal('0'))
            + (self.commission_cost or Decimal('0'))
        )

    @property
    def total_cost_price(self):
        return (self.cost_price or Decimal('0')) + self.additional_costs_total + self.maintenance_total

    @property
    def expected_profit(self):
        return (self.selling_price or Decimal('0')) - self.total_cost_price


class CarDocument(models.Model):
    DOCUMENT_REGISTRATION = 'registration'
    DOCUMENT_INSPECTION = 'inspection'
    DOCUMENT_SALE_CONTRACT = 'sale_contract'

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_REGISTRATION, 'الاستمارة'),
        (DOCUMENT_INSPECTION, 'الفحص'),
        (DOCUMENT_SALE_CONTRACT, 'المبايعة'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='documents', verbose_name='السيارة')
    document_type = models.CharField('نوع المستند', max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField('ملف المستند', upload_to='car_documents/%Y/%m/')
    upload_date = models.DateTimeField('تاريخ الرفع', auto_now_add=True)
    uploaded_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='تم الرفع بواسطة')

    class Meta:
        ordering = ['-upload_date', '-id']
        verbose_name = 'مستند سيارة'
        verbose_name_plural = 'مستندات السيارات'

    def __str__(self):
        return f"{self.car} - {self.get_document_type_display()}"


class FinancialContainer(models.Model):
    TYPE_MAIN_CASH = 'main_cash'
    TYPE_CUSTODY = 'custody'
    TYPE_BANK = 'bank'

    CONTAINER_TYPE_CHOICES = [
        (TYPE_MAIN_CASH, 'خزينة رئيسية'),
        (TYPE_CUSTODY, 'عهدة موظف'),
        (TYPE_BANK, 'حساب بنكي'),
    ]

    name = models.CharField('اسم الوعاء المالي', max_length=120)
    container_type = models.CharField('نوع الوعاء', max_length=20, choices=CONTAINER_TYPE_CHOICES)
    currency = models.CharField('العملة', max_length=3, choices=Car.CURRENCY_CHOICES, default='SR')
    linked_account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.PROTECT,
        related_name='financial_containers',
        verbose_name='الحساب المرتبط',
    )
    opening_balance = models.DecimalField('الرصيد الافتتاحي', max_digits=12, decimal_places=2, default=Decimal('0'))
    is_active = models.BooleanField('نشط', default=True)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'وعاء مالي'
        verbose_name_plural = 'الأوعية المالية'

    def __str__(self):
        return f"{self.name} ({self.get_container_type_display()})"

class Expense(models.Model):
    EXPENSE_TYPES = [
        ('rent', 'إيجار'),
        ('utility', 'كهرباء ومياه'),
        ('salary', 'رواتب'),
        ('maintenance', 'صيانة سيارات'),
        ('other', 'أخرى'),
    ]

    title = models.CharField("عنوان المصروف", max_length=100)
    car = models.ForeignKey('Car', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses', verbose_name='السيارة المرتبطة')
    amount = models.DecimalField("المبلغ", max_digits=10, decimal_places=2)
    expense_type = models.CharField("نوع المصروف", max_length=20, choices=EXPENSE_TYPES)
    date = models.DateField("التاريخ", auto_now_add=True)
    notes = models.TextField("ملاحظات إضافية", blank=True)

    def __str__(self):
        return f"{self.title} - {self.amount}"


class GeneralExpense(models.Model):
    CATEGORY_RENT = 'rent'
    CATEGORY_SALARY = 'salary'
    CATEGORY_BILLS = 'bills'
    CATEGORY_OTHER = 'other'

    CATEGORY_CHOICES = [
        (CATEGORY_RENT, 'إيجار'),
        (CATEGORY_SALARY, 'رواتب'),
        (CATEGORY_BILLS, 'فواتير'),
        (CATEGORY_OTHER, 'أخرى'),
    ]

    title = models.CharField('العنوان', max_length=120)
    category = models.CharField('التصنيف', max_length=20, choices=CATEGORY_CHOICES)
    amount = models.DecimalField('المبلغ', max_digits=12, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, choices=Car.CURRENCY_CHOICES, default='SR')
    expense_date = models.DateField('التاريخ', default=timezone.localdate)
    description = models.TextField('الوصف', blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='تمت الإضافة بواسطة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-id']
        verbose_name = 'مصروف عام'
        verbose_name_plural = 'المصروفات العامة'

    def __str__(self):
        return f"{self.title} - {self.amount} {self.currency}"


# جدول العملاء
class Customer(models.Model):
    name = models.CharField("اسم العميل", max_length=100)
    phone = models.CharField("رقم الهاتف", max_length=20)
    national_id = models.CharField("رقم الهوية", max_length=20, unique=True)

    def __str__(self):
        return self.name

# جدول عمليات البيع
class Sale(models.Model):
    car = models.OneToOneField(Car, on_delete=models.CASCADE, verbose_name="السيارة")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name="العميل")
    sales_employee = models.ForeignKey(
        'Employee',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales',
        verbose_name='الموظف المسؤول',
    )
    sale_price = models.DecimalField("سعر البيع النهائي", max_digits=10, decimal_places=2)
    sale_date = models.DateTimeField("تاريخ البيع", auto_now_add=True)
    amount_paid = models.DecimalField("المبلغ المدفوع", max_digits=12, decimal_places=2, default=0)
    debt_due_date = models.DateField('تاريخ استحقاق المديونية', null=True, blank=True)
    sale_contract_image = models.ImageField("صورة عقد البيع الموقّع", upload_to='sale_contracts/', null=True, blank=True)

    # دالة حسابية لمعرفة المتبقي تلقائياً
    @property
    def remaining_amount(self):
        return self.sale_price - self.amount_paid

    @property
    def is_fully_paid(self):
        return self.amount_paid >= self.sale_price

    @property
    def actual_profit(self):
        car_total_cost = self.car.total_cost_price if self.car_id else Decimal('0')
        return (self.sale_price or Decimal('0')) - (car_total_cost or Decimal('0'))

    def __str__(self):
        return f"بيع {self.car} إلى {self.customer}"


class SaleInstallment(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PARTIAL = 'partial'
    STATUS_PAID = 'paid'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'مستحق'),
        (STATUS_PARTIAL, 'مسدد جزئياً'),
        (STATUS_PAID, 'مسدد'),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='installments', verbose_name='عملية البيع')
    installment_order = models.PositiveIntegerField('ترتيب القسط', default=1)
    due_date = models.DateField('تاريخ الاستحقاق')
    amount = models.DecimalField('قيمة القسط', max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField('المبلغ المسدد', max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField('الحالة', max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    note = models.CharField('ملاحظة', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'installment_order', 'id']
        verbose_name = 'قسط بيع'
        verbose_name_plural = 'أقساط البيع'
        constraints = [
            models.UniqueConstraint(fields=['sale', 'installment_order'], name='uniq_sale_installment_order')
        ]

    @property
    def remaining_amount(self):
        return (self.amount or Decimal('0')) - (self.paid_amount or Decimal('0'))

    def __str__(self):
        return f"قسط {self.installment_order} - {self.sale}"


class DebtPayment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments', verbose_name='عملية البيع')
    receipt_number = models.CharField('رقم السند', max_length=30, unique=True)
    payment_date = models.DateField('تاريخ السداد')
    paid_amount = models.DecimalField('المبلغ المسدد', max_digits=12, decimal_places=2)
    is_deleted = models.BooleanField('محذوف ناعماً', default=False)
    deleted_at = models.DateTimeField('تاريخ الحذف', null=True, blank=True)
    deleted_by = models.CharField('تم الحذف بواسطة', max_length=150, blank=True)
    deletion_note = models.CharField('سبب الحذف', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"{self.receipt_number} - {self.sale}"


class FinanceVoucher(models.Model):
    VOUCHER_TYPES = [
        ('receipt', 'سند قبض'),
        ('payment', 'سند دفع'),
        ('operating', 'مصروفات تشغيلية'),
        ('settlement', 'سند تسديد'),
        ('maintenance', 'قيد صيانة سيارات'),
    ]

    ACCOUNT_NONE = 'none'
    ACCOUNT_OPERATING_EXPENSES = 'operating_expenses'
    ACCOUNT_MAINTENANCE_SOLD_CARS = 'maintenance_sold_cars'
    ACCOUNT_CASH_BOX = 'cash_box'
    ACCOUNT_BANK = 'bank'

    ACCOUNT_CHOICES = [
        (ACCOUNT_NONE, 'غير محدد'),
        (ACCOUNT_OPERATING_EXPENSES, 'المصروفات التشغيلية'),
        (ACCOUNT_MAINTENANCE_SOLD_CARS, 'مصروفات صيانة السيارات المباعة'),
        (ACCOUNT_CASH_BOX, 'الصندوق'),
        (ACCOUNT_BANK, 'البنك'),
    ]

    voucher_type = models.CharField('نوع السند', max_length=20, choices=VOUCHER_TYPES)
    voucher_number = models.CharField('رقم السند', max_length=30, unique=True)
    voucher_date = models.DateField('تاريخ السند')
    person_name = models.CharField('الاسم', max_length=150)
    amount = models.DecimalField('المبلغ', max_digits=12, decimal_places=2)
    currency = models.CharField('العملة', max_length=3, choices=Car.CURRENCY_CHOICES, default='SR')
    reason = models.CharField('البيان', max_length=255, blank=True)
    linked_car = models.ForeignKey(
        Car,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finance_vouchers',
        verbose_name='مركز التكلفة (السيارة)',
    )
    financial_container = models.ForeignKey(
        FinancialContainer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vouchers',
        verbose_name='الوعاء المالي',
    )
    supporting_document = models.FileField(
        'المستند المرفق',
        upload_to='voucher_docs/%Y/%m/',
        null=True,
        blank=True,
    )
    debit_account = models.CharField('الحساب المدين', max_length=40, choices=ACCOUNT_CHOICES, default=ACCOUNT_NONE, blank=True)
    credit_account = models.CharField('الحساب الدائن', max_length=40, choices=ACCOUNT_CHOICES, default=ACCOUNT_NONE, blank=True)
    is_deleted = models.BooleanField('محذوف ناعماً', default=False)
    deleted_at = models.DateTimeField('تاريخ الحذف', null=True, blank=True)
    deleted_by = models.CharField('تم الحذف بواسطة', max_length=150, blank=True)
    deletion_note = models.CharField('سبب الحذف', max_length=255, blank=True)
    reversed_from = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversal_entries',
        verbose_name='قيد عكسي لسند',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-voucher_date', '-created_at']

    def __str__(self):
        return f"{self.voucher_number} - {self.get_voucher_type_display()}"


class CarMaintenance(models.Model):
    MAINTENANCE_TYPES = [
        ('mechanical', 'ميكانيكا'),
        ('bodywork', 'سمكرة'),
        ('polish', 'تلميع'),
    ]

    PAYMENT_METHODS = [
        ('cash', 'الصندوق'),
        ('bank', 'البنك'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='maintenance_records', verbose_name='السيارة')
    amount = models.DecimalField('مبلغ الصيانة', max_digits=12, decimal_places=2)
    maintenance_type = models.CharField('نوع الصيانة', max_length=20, choices=MAINTENANCE_TYPES)
    operation_date = models.DateField('تاريخ العملية', default=timezone.localdate)
    supplier_workshop = models.CharField('المورد/الورشة', max_length=150)
    payment_method = models.CharField('طريقة الدفع', max_length=10, choices=PAYMENT_METHODS, default='cash')
    invoice_image = models.ImageField('صورة الفاتورة', upload_to='maintenance_invoices/')
    added_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='الموظف الذي أضاف المصروف')
    journal_voucher = models.OneToOneField(
        FinanceVoucher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='maintenance_record',
        verbose_name='القيد المحاسبي',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-operation_date', '-id']
        verbose_name = 'مصروف صيانة سيارة'
        verbose_name_plural = 'مصروفات صيانة السيارات'

    def __str__(self):
        return f"{self.car} - {self.amount}"

    def clean(self):
        if self.car_id and self.car.is_sold:
            raise ValidationError({'car': 'لا يمكن إضافة مصروف صيانة لسيارة مباعة.'})

    def _build_voucher_number(self):
        return f"MNT-{self.id:06d}"

    def _build_voucher_reason(self):
        payment_account = dict(self.PAYMENT_METHODS).get(self.payment_method, 'الصندوق')
        return (
            f"صيانة سيارة {self.car.brand} {self.car.model_name} ({self.car.vin}) - "
            f"مدين: مصروفات صيانة السيارات المباعة / دائن: {payment_account}"
        )

    def _sync_journal_voucher(self):
        credit_account = (
            FinanceVoucher.ACCOUNT_CASH_BOX
            if self.payment_method == 'cash'
            else FinanceVoucher.ACCOUNT_BANK
        )

        preferred_container_type = (
            FinancialContainer.TYPE_MAIN_CASH
            if self.payment_method == 'cash'
            else FinancialContainer.TYPE_BANK
        )
        linked_container = (
            FinancialContainer.objects.filter(
                container_type=preferred_container_type,
                currency=self.car.currency,
                is_active=True,
            ).first()
            or FinancialContainer.objects.filter(container_type=preferred_container_type, is_active=True).first()
        )

        voucher_defaults = {
            'voucher_type': 'maintenance',
            'voucher_date': self.operation_date,
            'person_name': self.supplier_workshop,
            'amount': self.amount,
            'currency': self.car.currency,
            'reason': self._build_voucher_reason(),
            'linked_car_id': self.car_id,
            'financial_container_id': linked_container.pk if linked_container else None,
            'supporting_document': self.invoice_image.name if self.invoice_image else '',
            'debit_account': FinanceVoucher.ACCOUNT_MAINTENANCE_SOLD_CARS,
            'credit_account': credit_account,
        }

        if self.journal_voucher_id:
            FinanceVoucher.objects.filter(pk=self.journal_voucher_id).update(**voucher_defaults)
            return

        voucher = FinanceVoucher.objects.create(
            voucher_number=self._build_voucher_number(),
            **voucher_defaults,
        )
        type(self).objects.filter(pk=self.pk).update(journal_voucher=voucher)
        self.journal_voucher_id = voucher.pk

    def save(self, *args, **kwargs):
        if self.car_id and self.car.is_sold:
            raise ValidationError('لا يمكن إضافة مصروف صيانة لسيارة مباعة.')
        super().save(*args, **kwargs)
        self._sync_journal_voucher()


class JournalEntry(models.Model):
    entry_number = models.CharField('رقم القيد', max_length=40, unique=True)
    entry_date = models.DateField('تاريخ القيد')
    description = models.CharField('وصف القيد', max_length=255)
    source_model = models.CharField('مصدر القيد', max_length=80, blank=True)
    source_pk = models.CharField('معرف المصدر', max_length=64, blank=True)
    source_reference = models.CharField('مرجع المصدر', max_length=80, blank=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_entries',
        verbose_name='تم الإنشاء بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_date', '-id']
        verbose_name = 'قيد يومية'
        verbose_name_plural = 'قيود اليومية'

    def __str__(self):
        return f"{self.entry_number} - {self.entry_date}"


class JournalEntryLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines', verbose_name='القيد')
    account = models.ForeignKey(FinancialAccount, on_delete=models.PROTECT, related_name='journal_lines', verbose_name='الحساب')
    line_description = models.CharField('بيان السطر', max_length=255, blank=True)
    debit = models.DecimalField('مدين', max_digits=14, decimal_places=2, default=Decimal('0'))
    credit = models.DecimalField('دائن', max_digits=14, decimal_places=2, default=Decimal('0'))
    currency = models.CharField('العملة', max_length=3, choices=Car.CURRENCY_CHOICES, default='SR')
    container = models.ForeignKey(
        FinancialContainer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_lines',
        verbose_name='الوعاء المالي',
    )
    car = models.ForeignKey(
        Car,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='journal_lines',
        verbose_name='مركز التكلفة (السيارة)',
    )

    class Meta:
        ordering = ['entry_id', 'id']
        verbose_name = 'سطر قيد'
        verbose_name_plural = 'سطور القيود'

    def __str__(self):
        return f"{self.entry.entry_number} - {self.account.code}"

    def clean(self):
        debit_value = self.debit or Decimal('0')
        credit_value = self.credit or Decimal('0')
        if debit_value < 0 or credit_value < 0:
            raise ValidationError('لا يمكن أن تكون قيم المدين/الدائن سالبة.')
        if debit_value == Decimal('0') and credit_value == Decimal('0'):
            raise ValidationError('يجب إدخال قيمة مدين أو دائن في سطر القيد.')
        if debit_value > Decimal('0') and credit_value > Decimal('0'):
            raise ValidationError('سطر القيد الواحد لا يمكن أن يحتوي مدين ودائن معًا.')


class AccountLedger(models.Model):
    REFERENCE_SALE = 'sale'
    REFERENCE_VOUCHER = 'voucher'
    REFERENCE_MAINTENANCE = 'maintenance'
    REFERENCE_EXPENSE = 'expense'
    REFERENCE_OTHER = 'other'

    REFERENCE_TYPE_CHOICES = [
        (REFERENCE_SALE, 'بيع'),
        (REFERENCE_VOUCHER, 'سند'),
        (REFERENCE_MAINTENANCE, 'صيانة'),
        (REFERENCE_EXPENSE, 'مصروف'),
        (REFERENCE_OTHER, 'أخرى'),
    ]

    account = models.ForeignKey(
        FinancialAccount,
        on_delete=models.PROTECT,
        related_name='ledger_entries',
        verbose_name='الحساب المالي',
    )
    journal_line = models.OneToOneField(
        JournalEntryLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entry',
        verbose_name='سطر القيد المرتبط',
    )
    transaction_date = models.DateField('التاريخ')
    debit = models.DecimalField('قيمة المدين', max_digits=14, decimal_places=2, default=Decimal('0'))
    credit = models.DecimalField('قيمة الدائن', max_digits=14, decimal_places=2, default=Decimal('0'))
    balance_after = models.DecimalField('الرصيد بعد العملية', max_digits=14, decimal_places=2, default=Decimal('0'))
    reference_type = models.CharField(
        'نوع المرجع',
        max_length=20,
        choices=REFERENCE_TYPE_CHOICES,
        default=REFERENCE_OTHER,
    )
    reference_id = models.CharField('معرف العملية المرجعية', max_length=64, blank=True)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['transaction_date', 'id']
        indexes = [
            models.Index(fields=['account', 'transaction_date', 'id']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
        verbose_name = 'دفتر أستاذ عام'
        verbose_name_plural = 'دفتر الأستاذ العام'

    def __str__(self):
        return f"{self.account.code} @ {self.transaction_date}"


class CustomerAccount(models.Model):
    customer = models.OneToOneField(
        Customer,
        on_delete=models.CASCADE,
        related_name='account_summary',
        verbose_name='العميل',
    )
    total_debt = models.DecimalField('إجمالي الديون', max_digits=14, decimal_places=2, default=Decimal('0'))
    total_paid = models.DecimalField('إجمالي المدفوع', max_digits=14, decimal_places=2, default=Decimal('0'))
    current_balance = models.DecimalField('الرصيد الحالي', max_digits=14, decimal_places=2, default=Decimal('0'))
    last_payment_date = models.DateField('تاريخ آخر سداد', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'حساب عميل'
        verbose_name_plural = 'حسابات العملاء'

    def __str__(self):
        return f"{self.customer.name} - {self.current_balance}"


class Supplier(models.Model):
    name = models.CharField('اسم المورد', max_length=150)
    phone = models.CharField('الهاتف', max_length=30, blank=True)
    tax_number = models.CharField('الرقم الضريبي', max_length=60, blank=True)
    address = models.CharField('العنوان', max_length=255, blank=True)
    is_active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'مورد'
        verbose_name_plural = 'الموردون'

    def __str__(self):
        return self.name


class SupplierInvoice(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PARTIAL = 'partial'
    STATUS_PAID = 'paid'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'مستحق'),
        (STATUS_PARTIAL, 'مسدد جزئياً'),
        (STATUS_PAID, 'مسدد بالكامل'),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='invoices', verbose_name='المورد')
    car = models.ForeignKey(Car, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplier_invoices', verbose_name='السيارة')
    invoice_number = models.CharField('رقم الفاتورة', max_length=40, unique=True)
    invoice_date = models.DateField('تاريخ الفاتورة', default=timezone.localdate)
    due_date = models.DateField('تاريخ الاستحقاق', null=True, blank=True)
    total_amount = models.DecimalField('إجمالي الفاتورة', max_digits=14, decimal_places=2)
    paid_amount = models.DecimalField('المبلغ المسدد', max_digits=14, decimal_places=2, default=Decimal('0'))
    status = models.CharField('الحالة', max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-invoice_date', '-id']
        verbose_name = 'فاتورة مورد'
        verbose_name_plural = 'فواتير الموردين'

    @property
    def remaining_amount(self):
        return (self.total_amount or Decimal('0')) - (self.paid_amount or Decimal('0'))

    def __str__(self):
        return f"{self.invoice_number} - {self.supplier.name}"

    def save(self, *args, **kwargs):
        remaining = (self.total_amount or Decimal('0')) - (self.paid_amount or Decimal('0'))
        if remaining <= Decimal('0'):
            self.status = self.STATUS_PAID
        elif self.paid_amount and self.paid_amount > Decimal('0'):
            self.status = self.STATUS_PARTIAL
        else:
            self.status = self.STATUS_PENDING
        super().save(*args, **kwargs)


class SupplierPayment(models.Model):
    METHOD_CASH = 'cash'
    METHOD_BANK = 'bank'

    METHOD_CHOICES = [
        (METHOD_CASH, 'نقدي'),
        (METHOD_BANK, 'تحويل بنكي'),
    ]

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='payments', verbose_name='المورد')
    invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name='الفاتورة',
    )
    payment_number = models.CharField('رقم الدفعة', max_length=40, unique=True)
    payment_date = models.DateField('تاريخ الدفع', default=timezone.localdate)
    amount = models.DecimalField('المبلغ', max_digits=14, decimal_places=2)
    payment_method = models.CharField('طريقة الدفع', max_length=10, choices=METHOD_CHOICES, default=METHOD_CASH)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = 'دفعة مورد'
        verbose_name_plural = 'دفعات الموردين'

    def __str__(self):
        return self.payment_number


class InventoryTransaction(models.Model):
    TYPE_PURCHASE = 'purchase'
    TYPE_SALE = 'sale'
    TYPE_ADJUSTMENT = 'adjustment'
    TYPE_MAINTENANCE = 'maintenance'

    TYPE_CHOICES = [
        (TYPE_PURCHASE, 'شراء'),
        (TYPE_SALE, 'بيع'),
        (TYPE_ADJUSTMENT, 'تعديل'),
        (TYPE_MAINTENANCE, 'صيانة'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='inventory_transactions', verbose_name='السيارة')
    transaction_type = models.CharField('نوع الحركة', max_length=20, choices=TYPE_CHOICES)
    transaction_date = models.DateField('التاريخ', default=timezone.localdate)
    cost = models.DecimalField('التكلفة', max_digits=14, decimal_places=2, default=Decimal('0'))
    reference_type = models.CharField('نوع المرجع', max_length=40, blank=True)
    reference_id = models.CharField('المرجع المرتبط بالعملية', max_length=64, blank=True)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['transaction_date', 'id']
        verbose_name = 'حركة مخزون'
        verbose_name_plural = 'حركات المخزون'

    def __str__(self):
        return f"{self.car.vin} - {self.get_transaction_type_display()}"


class TaxRate(models.Model):
    name = models.CharField('اسم الضريبة', max_length=80, unique=True)
    rate_percent = models.DecimalField('نسبة الضريبة', max_digits=5, decimal_places=2, default=Decimal('0'))
    is_active = models.BooleanField('حالة التفعيل', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'ضريبة'
        verbose_name_plural = 'الضرائب'

    def __str__(self):
        return f"{self.name} ({self.rate_percent}%)"


class Invoice(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ISSUED = 'issued'
    STATUS_PAID = 'paid'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'مسودة'),
        (STATUS_ISSUED, 'مُصدرة'),
        (STATUS_PAID, 'مسددة'),
        (STATUS_CANCELLED, 'ملغاة'),
    ]

    sale = models.OneToOneField(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice', verbose_name='عملية البيع')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices', verbose_name='العميل')
    invoice_number = models.CharField('رقم الفاتورة', max_length=40, unique=True)
    invoice_date = models.DateField('تاريخ الفاتورة', default=timezone.localdate)
    due_date = models.DateField('تاريخ الاستحقاق', null=True, blank=True)
    currency = models.CharField('العملة', max_length=3, choices=Car.CURRENCY_CHOICES, default='SR')
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices', verbose_name='الضريبة')
    subtotal = models.DecimalField('الإجمالي قبل الضريبة', max_digits=14, decimal_places=2, default=Decimal('0'))
    tax_amount = models.DecimalField('قيمة الضريبة', max_digits=14, decimal_places=2, default=Decimal('0'))
    total_amount = models.DecimalField('الإجمالي النهائي', max_digits=14, decimal_places=2, default=Decimal('0'))
    status = models.CharField('الحالة', max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-invoice_date', '-id']
        verbose_name = 'فاتورة'
        verbose_name_plural = 'الفواتير'

    def __str__(self):
        return self.invoice_number

    def recalculate_totals(self):
        subtotal = self.lines.aggregate(total=models.Sum('line_total'))['total'] or Decimal('0')
        tax_amount = Decimal('0')
        if self.tax_rate_id and self.tax_rate and self.tax_rate.is_active:
            tax_amount = (subtotal * (self.tax_rate.rate_percent or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'))
        total_amount = subtotal + tax_amount

        db_alias = (getattr(self._state, 'db', '') or '').strip()
        invoice_manager = type(self).objects.using(db_alias) if db_alias else type(self).objects

        invoice_manager.filter(pk=self.pk).update(
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
        )
        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.total_amount = total_amount


class InvoiceLine(models.Model):
    TYPE_CAR = 'car'
    TYPE_TRANSPORT = 'transport'
    TYPE_COMMISSION = 'commission'
    TYPE_SERVICE = 'service'
    TYPE_REGISTRATION = 'registration'
    TYPE_OTHER = 'other'

    TYPE_CHOICES = [
        (TYPE_CAR, 'سيارة'),
        (TYPE_TRANSPORT, 'رسوم نقل'),
        (TYPE_COMMISSION, 'عمولات'),
        (TYPE_SERVICE, 'خدمات إضافية'),
        (TYPE_REGISTRATION, 'مصاريف تسجيل'),
        (TYPE_OTHER, 'أخرى'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines', verbose_name='الفاتورة')
    car = models.ForeignKey(Car, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice_lines', verbose_name='السيارة')
    line_type = models.CharField('نوع البند', max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER)
    description = models.CharField('الوصف', max_length=255)
    quantity = models.DecimalField('الكمية', max_digits=10, decimal_places=2, default=Decimal('1'))
    unit_price = models.DecimalField('سعر الوحدة', max_digits=14, decimal_places=2)
    line_total = models.DecimalField('إجمالي السطر', max_digits=14, decimal_places=2, default=Decimal('0'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'بند فاتورة'
        verbose_name_plural = 'بنود الفواتير'

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.description}"

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)


class Currency(models.Model):
    code = models.CharField('رمز العملة', max_length=6, unique=True)
    name = models.CharField('اسم العملة', max_length=80)
    symbol = models.CharField('الرمز', max_length=8, blank=True)
    is_active = models.BooleanField('نشطة', default=True)

    class Meta:
        ordering = ['code']
        verbose_name = 'عملة'
        verbose_name_plural = 'العملات'

    def __str__(self):
        return self.code


class ExchangeRate(models.Model):
    from_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='source_rates', verbose_name='من عملة')
    to_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='target_rates', verbose_name='إلى عملة')
    rate_date = models.DateField('تاريخ السعر', default=timezone.localdate)
    rate = models.DecimalField('سعر الصرف', max_digits=18, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-rate_date', 'from_currency__code', 'to_currency__code']
        constraints = [
            models.UniqueConstraint(
                fields=['from_currency', 'to_currency', 'rate_date'],
                name='uniq_exchange_rate_daily_pair',
            )
        ]
        verbose_name = 'سعر صرف'
        verbose_name_plural = 'أسعار الصرف'

    def __str__(self):
        return f"{self.from_currency.code}/{self.to_currency.code} @ {self.rate_date}"


class EmployeeRole(models.Model):
    name = models.CharField('المسمى الوظيفي', max_length=80, unique=True)
    description = models.CharField('الوصف', max_length=255, blank=True)
    is_active = models.BooleanField('نشط', default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'دور وظيفي'
        verbose_name_plural = 'الأدوار الوظيفية'

    def __str__(self):
        return self.name


class Employee(models.Model):
    user = models.OneToOneField(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='employee_profile',
        verbose_name='الحساب',
    )
    role = models.ForeignKey(EmployeeRole, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees', verbose_name='الدور')
    full_name = models.CharField('الاسم', max_length=150)
    phone = models.CharField('الهاتف', max_length=30, blank=True)
    hire_date = models.DateField('تاريخ التعيين', default=timezone.localdate)
    is_active = models.BooleanField('نشط', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name', 'id']
        verbose_name = 'موظف'
        verbose_name_plural = 'الموظفون'

    def __str__(self):
        return self.full_name


class EmployeeCommission(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='commission_periods', verbose_name='الموظف')
    period_start = models.DateField('من تاريخ')
    period_end = models.DateField('إلى تاريخ')
    amount = models.DecimalField('قيمة العمولة', max_digits=14, decimal_places=2, default=Decimal('0'))
    is_paid = models.BooleanField('تم الصرف', default=False)
    paid_at = models.DateField('تاريخ الصرف', null=True, blank=True)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)

    class Meta:
        ordering = ['-period_start', '-id']
        verbose_name = 'عمولة موظف دورية'
        verbose_name_plural = 'عمولات الموظفين الدورية'

    def __str__(self):
        return f"{self.employee.full_name} ({self.period_start} - {self.period_end})"


class SalesCommission(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_PAID = 'paid'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'قيد المراجعة'),
        (STATUS_APPROVED, 'معتمدة'),
        (STATUS_PAID, 'مصروفة'),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='sales_commissions', verbose_name='عملية البيع')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='sales_commissions', verbose_name='الموظف')
    commission_rate = models.DecimalField('نسبة العمولة', max_digits=5, decimal_places=2, default=Decimal('0'))
    commission_amount = models.DecimalField('قيمة العمولة', max_digits=14, decimal_places=2, default=Decimal('0'))
    payout_status = models.CharField('حالة الصرف', max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    paid_at = models.DateField('تاريخ الصرف', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'عمولة بيع'
        verbose_name_plural = 'عمولات المبيعات'

    def __str__(self):
        return f"{self.sale_id} - {self.employee.full_name}"

    def save(self, *args, **kwargs):
        if self.sale_id and self.commission_rate is not None:
            self.commission_amount = (
                (self.sale.sale_price or Decimal('0'))
                * (self.commission_rate or Decimal('0'))
                / Decimal('100')
            ).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class CarHistory(models.Model):
    EVENT_PURCHASE = 'purchase'
    EVENT_MAINTENANCE = 'maintenance'
    EVENT_TRANSFER = 'transfer'
    EVENT_LISTED = 'listed'
    EVENT_SOLD = 'sold'

    EVENT_CHOICES = [
        (EVENT_PURCHASE, 'شراء'),
        (EVENT_MAINTENANCE, 'صيانة'),
        (EVENT_TRANSFER, 'نقل'),
        (EVENT_LISTED, 'عرض للبيع'),
        (EVENT_SOLD, 'بيع'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='history_items', verbose_name='السيارة')
    event_type = models.CharField('نوع الحدث', max_length=20, choices=EVENT_CHOICES)
    event_date = models.DateField('تاريخ الحدث', default=timezone.localdate)
    reference_type = models.CharField('نوع المرجع', max_length=40, blank=True)
    reference_id = models.CharField('معرف المرجع', max_length=64, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-event_date', '-id']
        verbose_name = 'سجل تاريخ السيارة'
        verbose_name_plural = 'سجل تاريخ السيارات'

    def __str__(self):
        return f"{self.car.vin} - {self.get_event_type_display()}"


class CarReservation(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='reservations', verbose_name='السيارة')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='car_reservations', verbose_name='العميل')
    reservation_date = models.DateField('تاريخ الحجز', default=timezone.localdate)
    expiry_date = models.DateField('تاريخ انتهاء الحجز')
    deposit_amount = models.DecimalField('مبلغ العربون', max_digits=12, decimal_places=2, default=Decimal('0'))
    is_active = models.BooleanField('الحجز نشط', default=True)
    notes = models.CharField('ملاحظات', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reservation_date', '-id']
        verbose_name = 'حجز سيارة'
        verbose_name_plural = 'حجوزات السيارات'

    def __str__(self):
        return f"{self.car.vin} - {self.customer.name}"

    def clean(self):
        if self.expiry_date and self.reservation_date and self.expiry_date < self.reservation_date:
            raise ValidationError({'expiry_date': 'تاريخ انتهاء الحجز يجب أن يكون بعد تاريخ الحجز.'})

        if self.is_active and self.car_id:
            overlapping = type(self).objects.filter(
                car_id=self.car_id,
                is_active=True,
            ).exclude(pk=self.pk)
            if overlapping.exists():
                raise ValidationError({'car': 'توجد عملية حجز نشطة لهذه السيارة بالفعل.'})


class CarEvaluation(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='evaluations', verbose_name='السيارة')
    evaluation_date = models.DateField('تاريخ التقييم', default=timezone.localdate)
    market_value = models.DecimalField('القيمة السوقية', max_digits=14, decimal_places=2)
    evaluator_name = models.CharField('المقيّم', max_length=150, blank=True)
    notes = models.TextField('ملاحظات', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-evaluation_date', '-id']
        verbose_name = 'تقييم سيارة'
        verbose_name_plural = 'تقييمات السيارات'

    def __str__(self):
        return f"{self.car.vin} - {self.market_value}"


class CarLocation(models.Model):
    car = models.OneToOneField(Car, on_delete=models.CASCADE, related_name='location', verbose_name='السيارة')
    showroom_name = models.CharField('المعرض', max_length=120)
    row_label = models.CharField('الصف', max_length=40)
    spot_label = models.CharField('الموقع', max_length=40)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['showroom_name', 'row_label', 'spot_label']
        constraints = [
            models.UniqueConstraint(
                fields=['showroom_name', 'row_label', 'spot_label'],
                name='uniq_car_location_spot',
            )
        ]
        verbose_name = 'موقع سيارة'
        verbose_name_plural = 'مواقع السيارات'

    def __str__(self):
        return f"{self.showroom_name} - {self.row_label}/{self.spot_label}"


class OperationLog(models.Model):
    operation = models.CharField('العملية', max_length=255)
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='الحساب')
    created_at = models.DateTimeField('التاريخ والوقت', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        username = self.user.username if self.user else 'غير معروف'
        return f"{self.operation} - {username}"


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='الحساب')
    tenant_id = models.SlugField('معرف المعرض', max_length=50, blank=True)
    action = models.CharField('الإجراء', max_length=30)
    target_model = models.CharField('اسم النموذج', max_length=80)
    target_pk = models.CharField('معرف السجل', max_length=64, blank=True)
    before_data = models.JSONField('القيم السابقة', null=True, blank=True)
    after_data = models.JSONField('القيم الجديدة', null=True, blank=True)
    ip_address = models.CharField('عنوان IP', max_length=64, blank=True)
    device_type = models.CharField('نوع الجهاز', max_length=80, blank=True)
    browser = models.CharField('المتصفح', max_length=120, blank=True)
    geo_location = models.CharField('الموقع الجغرافي التقريبي', max_length=120, blank=True)
    request_path = models.CharField('المسار', max_length=255, blank=True)
    timestamp = models.DateTimeField('وقت العملية', auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'سجل تدقيق'
        verbose_name_plural = 'سجل التدقيق'

    def __str__(self):
        return f"{self.action} - {self.target_model} ({self.target_pk})"


class InterfaceAccess(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='interface_access', verbose_name='الحساب')
    can_access_dashboard = models.BooleanField('لوحة التحكم', default=True)
    can_access_cars = models.BooleanField('المعرض', default=True)
    can_access_reports = models.BooleanField('التقارير', default=True)
    can_access_debts = models.BooleanField('الديون', default=True)
    can_access_timeline = models.BooleanField('الجدول الزمني', default=True)
    can_access_system_users = models.BooleanField('حسابات المستخدمين', default=True)
    can_add_maintenance_expenses = models.BooleanField('إضافة مصروفات صيانة', default=False)

    class Meta:
        verbose_name = 'صلاحيات واجهات المستخدم'
        verbose_name_plural = 'صلاحيات واجهات المستخدمين'

    def __str__(self):
        return f"صلاحيات {self.user.username}"


class TenantUserGoogleIdentity(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE, related_name='google_identity', verbose_name='الحساب')
    google_sub = models.CharField('Google Subject ID', max_length=255, unique=True)
    google_email = models.EmailField('Google Email', max_length=254)
    email_verified = models.BooleanField('البريد موثق من Google', default=False)
    last_verified_at = models.DateTimeField('آخر تحقق', auto_now=True)
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'ربط حساب Google'
        verbose_name_plural = 'روابط حسابات Google'

    def __str__(self):
        return f"{self.user.username} -> {self.google_email}"


from django.db.models.signals import post_save
from django.dispatch import receiver

class Notification(models.Model):
    message = models.CharField("نص التنبيه", max_length=255)
    is_read = models.BooleanField("تمت القراءة", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at'] # التنبيهات الأحدث تظهر أولاً

    def __str__(self):
        return self.message


# previously a Profile model was used for account-type based permissions
# that functionality has been removed, so no extra user model is needed.
# (related imports were cleared)

@receiver(post_save, sender=Sale)
def create_sale_notification(sender, instance, created, **kwargs):
    if created:
        if not instance.car.is_sold:
            instance.car.is_sold = True
            instance.car.save(update_fields=['is_sold'])

        remaining = instance.remaining_amount
        msg = (
            f"تم بيع السيارة {instance.car.vin} للعميل {instance.customer.name} "
            f"بقيمة {instance.sale_price}، المدفوع {instance.amount_paid}، المتبقي {remaining}."
        )
        Notification.objects.create(message=msg)

        if remaining > Decimal('0') and instance.debt_due_date:
            Notification.objects.create(
                message=f"تمت جدولة تنبيه القسط الأول للبيع رقم {instance.pk} بتاريخ {instance.debt_due_date}."
            )