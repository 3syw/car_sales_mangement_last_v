from django.core.management.base import BaseCommand, CommandError

from sales.models import PlatformTenant
from sales.platform_audit import write_platform_audit
from sales.tenant_database import normalize_tenant_id


class Command(BaseCommand):
    help = 'Marks a tenant as soft-deleted (deactivated without removing tenant database files).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=True, help='Tenant identifier')
        parser.add_argument('--actor', default='system', help='Actor username for audit tracking')
        parser.add_argument('--force', action='store_true', help='Required safety flag for soft delete operation')

    def handle(self, *args, **options):
        tenant_id = normalize_tenant_id(options['tenant_id'])
        actor = options['actor']

        if not options.get('force'):
            raise CommandError('Soft delete requires --force for safety.')

        tenant = PlatformTenant.objects.using('default').filter(tenant_id=tenant_id).first()
        if tenant is None:
            raise CommandError('Tenant not found.')

        if tenant.is_deleted:
            self.stdout.write('Tenant already soft-deleted.')
            return

        tenant.soft_delete(actor_username=actor)
        tenant.save(using='default', update_fields=['is_active', 'is_deleted', 'deleted_at', 'deleted_by'])

        write_platform_audit(
            event_type='tenant_soft_delete',
            tenant_id=tenant_id,
            actor_username=actor,
            notes='Tenant soft-deleted and access disabled',
        )

        self.stdout.write(self.style.SUCCESS(f'Tenant soft-deleted: {tenant_id}'))
