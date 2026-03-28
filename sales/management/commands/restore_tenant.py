import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.models import PlatformTenant, TenantBackupRecord
from sales.platform_audit import write_platform_audit
from sales.tenant_database import tenant_db_path, normalize_tenant_id


class Command(BaseCommand):
    help = 'Restores a tenant database from a selected backup file.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=True, help='Tenant identifier')
        parser.add_argument('--backup-path', required=False, help='Absolute path to backup sqlite file')
        parser.add_argument('--actor', default='system', help='Actor username for audit tracking')
        parser.add_argument('--force', action='store_true', help='Required safety flag for restore operation')

    def handle(self, *args, **options):
        tenant_id = normalize_tenant_id(options['tenant_id'])
        backup_path = options.get('backup_path')
        actor = options['actor']

        if not options.get('force'):
            raise CommandError('Restore requires --force for safety.')

        tenant = PlatformTenant.objects.using('default').filter(tenant_id=tenant_id, is_active=True).first()
        if tenant is None:
            raise CommandError('Tenant not found or inactive.')

        if backup_path:
            source_backup = Path(backup_path)
        else:
            latest_backup = TenantBackupRecord.objects.using('default').filter(tenant=tenant).order_by('-created_at').first()
            if latest_backup is None:
                raise CommandError('No backup records found for this tenant.')
            source_backup = Path(latest_backup.backup_file)

        if not source_backup.exists():
            raise CommandError(f'Backup file not found: {source_backup}')

        target_db = tenant_db_path(tenant_id)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_backup, target_db)

        write_platform_audit(
            event_type='tenant_restore',
            tenant_id=tenant_id,
            actor_username=actor,
            notes=f'Restored from: {source_backup.name}',
        )

        self.stdout.write(self.style.SUCCESS(f'Tenant restored from: {source_backup}'))
