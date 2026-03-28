import time

from django.core.management.base import BaseCommand

from sales.models import PlatformTenant, TenantMigrationRecord
from sales.platform_audit import write_platform_audit
from sales.tenant_database import migrate_tenant_database


class Command(BaseCommand):
    help = 'Runs migrations across all active tenant databases sequentially.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=False, help='Optional single tenant id')
        parser.add_argument('--actor', default='system', help='Actor username for audit tracking')

    def handle(self, *args, **options):
        actor = options['actor']
        tenant_id = options.get('tenant_id')

        queryset = PlatformTenant.objects.using('default').filter(is_active=True)
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id.strip().lower())

        tenants = list(queryset.order_by('tenant_id'))
        if not tenants:
            self.stdout.write('No active tenants found.')
            return

        success_count = 0
        failure_count = 0

        for tenant in tenants:
            start = time.perf_counter()
            status = 'success'
            details = 'Migration completed.'
            try:
                migrate_tenant_database(tenant.tenant_id)
                success_count += 1
                write_platform_audit(
                    event_type='tenant_migrate',
                    tenant_id=tenant.tenant_id,
                    actor_username=actor,
                    notes='Tenant migration success',
                )
            except Exception as exc:
                status = 'failed'
                details = str(exc)[:255]
                failure_count += 1
                write_platform_audit(
                    event_type='tenant_migrate',
                    tenant_id=tenant.tenant_id,
                    actor_username=actor,
                    notes=f'Tenant migration failed: {details}',
                )
            finally:
                duration_ms = int((time.perf_counter() - start) * 1000)
                TenantMigrationRecord.objects.using('default').create(
                    tenant=tenant,
                    status=status,
                    duration_ms=duration_ms,
                    details=details,
                )

        self.stdout.write(self.style.SUCCESS(
            f'Migration run completed. Success: {success_count}, Failed: {failure_count}'
        ))
