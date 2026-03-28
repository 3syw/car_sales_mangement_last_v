from django.core.management.base import BaseCommand, CommandError

from sales.models import PlatformTenant
from sales.platform_audit import write_platform_audit
from sales.tenant_database import normalize_tenant_id


class Command(BaseCommand):
    help = 'Restores a previously soft-deleted tenant and re-enables access.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=True, help='Tenant identifier')
        parser.add_argument('--actor', default='system', help='Actor username for audit tracking')

    def handle(self, *args, **options):
        tenant_id = normalize_tenant_id(options['tenant_id'])
        actor = options['actor']

        tenant = PlatformTenant.objects.using('default').filter(tenant_id=tenant_id).first()
        if tenant is None:
            raise CommandError('Tenant not found.')

        if not tenant.is_deleted and tenant.is_active:
            self.stdout.write('Tenant is already active.')
            return

        tenant.restore_soft_deleted()
        tenant.is_active = True
        tenant.save(using='default', update_fields=['is_active', 'is_deleted', 'deleted_at', 'deleted_by'])

        write_platform_audit(
            event_type='tenant_restore_soft_deleted',
            tenant_id=tenant_id,
            actor_username=actor,
            notes='Tenant restored from soft-delete',
        )

        self.stdout.write(self.style.SUCCESS(f'Tenant restored: {tenant_id}'))
