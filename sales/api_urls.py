from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import (
    AuditLogViewSet,
    AuthMeAPIView,
    AuthRefreshAPIView,
    AuthTokenAPIView,
    CarViewSet,
    DebtPaymentViewSet,
    FinanceVoucherViewSet,
    QueueDBIsolationAuditTaskAPIView,
    QueueFinancialConsistencyTaskAPIView,
    QueueTenantBackupTaskAPIView,
    QueueTenantSnapshotTaskAPIView,
    ReportsSummaryAPIView,
    SaleProcessAPIView,
    SaleViewSet,
    TaskStatusAPIView,
)


router = DefaultRouter()
router.register(r'cars', CarViewSet, basename='api-cars')
router.register(r'sales', SaleViewSet, basename='api-sales')
router.register(r'finance-vouchers', FinanceVoucherViewSet, basename='api-finance-vouchers')
router.register(r'debt-payments', DebtPaymentViewSet, basename='api-debt-payments')
router.register(r'audit-logs', AuditLogViewSet, basename='api-audit-logs')


urlpatterns = [
    path('auth/token/', AuthTokenAPIView.as_view(), name='api-auth-token'),
    path('auth/token/refresh/', AuthRefreshAPIView.as_view(), name='api-auth-token-refresh'),
    path('auth/me/', AuthMeAPIView.as_view(), name='api-auth-me'),
    path('', include(router.urls)),
    path('sales/process/', SaleProcessAPIView.as_view(), name='api-sales-process'),
    path('reports/summary/', ReportsSummaryAPIView.as_view(), name='api-reports-summary'),
    path('tasks/financial-consistency/', QueueFinancialConsistencyTaskAPIView.as_view(), name='api-task-financial-consistency'),
    path('tasks/tenant-backup/', QueueTenantBackupTaskAPIView.as_view(), name='api-task-tenant-backup'),
    path('tasks/db-isolation-audit/', QueueDBIsolationAuditTaskAPIView.as_view(), name='api-task-db-isolation-audit'),
    path('tasks/tenant-snapshot/', QueueTenantSnapshotTaskAPIView.as_view(), name='api-task-tenant-snapshot'),
    path('tasks/<str:task_id>/status/', TaskStatusAPIView.as_view(), name='api-task-status'),
]
