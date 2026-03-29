"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from sales.views import welcome, home, dashboard, export_sales_excel, export_financial_excel, export_timeline_excel, financial_report_charts_data, car_list, car_edit, car_detail, process_sale, financial_reports, car_profit_report, showroom_performance_report, inventory_turnover_report, stale_cars_report, audit_logs_report, export_audit_logs_excel, export_audit_logs_csv, financial_reports_detail, vouchers_reports, vouchers_list, receipt_voucher, payment_voucher, operating_expenses_voucher, general_expenses_management, digital_archive, inventory_reconciliation, debts_list, debt_aging_report, add_debt_payment, timeline_view, user_logout, register, user_login, admin_user_filters, system_users, available_cars_table, sold_cars_cards, sold_car_details, permissions_management, delete_system_user, platform_switch_tenant, platform_exit_impersonation, central_audit_monitor, daily_closing_control, cash_flow_projection, bank_reconciliation, financial_consistency_checker, chart_of_accounts, trial_balance_report, financial_containers_management, fiscal_period_closing_control, google_auth_start, google_auth_callback, user_theme_preference
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('healthz/', lambda request: HttpResponse('ok', content_type='text/plain'), name='healthz'),
    path('', welcome, name='welcome'),
    path('login/', user_login, name='login'),
    path('admin/login/', user_login, name='admin_login'),
    path('auth/google/start/', google_auth_start, name='google_auth_start'),
    path('auth/google/callback/', google_auth_callback, name='google_auth_callback'),
    path('ui/theme/', user_theme_preference, name='user_theme_preference'),
    path('admin/platform/login/', user_login, name='platform_owner_login'),
    path('admin/platform/switch-tenant/', platform_switch_tenant, name='platform_switch_tenant'),
    path('admin/platform/exit-tenant/', platform_exit_impersonation, name='platform_exit_impersonation'),
    path('admin/register/', register, name='register'),
    path('admin/auth/user/filters-search/', admin_user_filters, name='admin_user_filters'),
    path('admin/auth/user/list/', system_users, name='system_users'),
    path('admin/sales/car/available/', available_cars_table, name='available_cars_table'),
    path('admin/sales/car/sold/', sold_cars_cards, name='sold_cars_cards'),
    path('admin/sales/car/sold/<int:car_id>/details/', sold_car_details, name='sold_car_details'),
    path('admin/sales/permissions/', permissions_management, name='permissions_management'),
    path('admin/sales/permissions/delete-user/<int:user_id>/', delete_system_user, name='delete_system_user'),
    path('signup/', register, name='signup'),
    path('admin/', admin.site.urls),
    path('api/', include('sales.api_urls')),
    path('api/v1/', include(('sales.api_urls', 'sales'), namespace='api-v1')),
    path('home/', home, name='home'), # الصفحة الرئيسية بعد تسجيل الدخول
    path('dashboard/', dashboard, name='dashboard'),
    path('export-excel/', export_sales_excel, name='export_excel'),
    path('cars/', car_list, name='car_list'), # رابط قائمة السيارات
    path('cars/edit/<int:car_id>/', car_edit, name='car_edit'),
    path('cars/<int:car_id>/', car_detail, name='car_detail'),
    path('sales/process/', process_sale, name='process_sale'),
    path('sales/process/<int:car_id>/', process_sale, name='process_sale_car'),
    path('cars/reconciliation/', inventory_reconciliation, name='inventory_reconciliation'),
    path('archive/', digital_archive, name='digital_archive'),
    path('reports/', financial_reports, name='reports'),
    path('reports/advanced/car-profit/', car_profit_report, name='car_profit_report'),
    path('reports/advanced/showroom-performance/', showroom_performance_report, name='showroom_performance_report'),
    path('reports/advanced/inventory-turnover/', inventory_turnover_report, name='inventory_turnover_report'),
    path('reports/advanced/stale-cars/', stale_cars_report, name='stale_cars_report'),
    path('reports/audit-logs/', audit_logs_report, name='audit_logs_report'),
    path('reports/central-monitor/', central_audit_monitor, name='central_audit_monitor'),
    path('reports/audit-logs/export/excel/', export_audit_logs_excel, name='export_audit_logs_excel'),
    path('reports/audit-logs/export/csv/', export_audit_logs_csv, name='export_audit_logs_csv'),
    path('reports/financial/', financial_reports_detail, name='reports_financial'),
    path('reports/financial/cash-flow-projection/', cash_flow_projection, name='cash_flow_projection'),
    path('reports/financial/consistency-checker/', financial_consistency_checker, name='financial_consistency_checker'),
    path('reports/financial/chart-of-accounts/', chart_of_accounts, name='chart_of_accounts'),
    path('reports/financial/trial-balance/', trial_balance_report, name='trial_balance_report'),
    path('reports/financial/containers/', financial_containers_management, name='financial_containers'),
    path('reports/financial/fiscal-closing/', fiscal_period_closing_control, name='fiscal_period_closing'),
    path('reports/bank-reconciliation/', bank_reconciliation, name='bank_reconciliation'),
    path('reports/financial/export/', export_financial_excel, name='export_financial_excel'),
    path('reports/financial/charts-data/', financial_report_charts_data, name='financial_report_charts_data'),
    path('reports/financial/general-expenses/', general_expenses_management, name='general_expenses_management'),
    path('reports/vouchers/', vouchers_reports, name='reports_vouchers'),
    path('reports/vouchers/list/', vouchers_list, name='vouchers_list'),
    path('reports/daily-closing/', daily_closing_control, name='daily_closing'),
    path('reports/vouchers/receipt/', receipt_voucher, name='receipt_voucher'),
    path('reports/vouchers/payment/', payment_voucher, name='payment_voucher'),
    path('reports/vouchers/operating-expenses/', operating_expenses_voucher, name='operating_expenses_voucher'),
    path('debts/', debts_list, name='debts_list'),
    path('debts/aging/', debt_aging_report, name='debt_aging_report'),
    path('debts/<int:sale_id>/add-payment/', add_debt_payment, name='add_debt_payment'),
    path('timeline/', timeline_view, name='timeline'),
    path('timeline/export/', export_timeline_excel, name='export_timeline_excel'),
    path('logout/', user_logout, name='logout'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)