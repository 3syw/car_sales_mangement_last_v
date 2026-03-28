import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sales.models import PlatformTenant, TenantBackupRecord
from sales.platform_audit import write_platform_audit
from sales.tenant_database import tenant_db_path, normalize_tenant_id


class Command(BaseCommand):
    help = 'Creates an isolated backup for a specific tenant database.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=True, help='Tenant identifier')
        parser.add_argument('--actor', default='system', help='Actor username for audit tracking')

    def handle(self, *args, **options):
        tenant_id = normalize_tenant_id(options['tenant_id'])
        actor = options['actor']

        tenant = PlatformTenant.objects.using('default').filter(tenant_id=tenant_id, is_active=True).first()
        if tenant is None:
            raise CommandError('Tenant not found or inactive.')

        source_db = tenant_db_path(tenant_id)
        if not source_db.exists():
            raise CommandError(f'Tenant database file not found: {source_db}')

        backup_dir = Path(settings.BASE_DIR) / 'backups' / 'tenants' / tenant_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'{tenant_id}_{timestamp}.sqlite3'
        shutil.copy2(source_db, backup_file)

        file_size = int(backup_file.stat().st_size)
        TenantBackupRecord.objects.using('default').create(
            tenant=tenant,
            backup_file=str(backup_file),
            file_size_bytes=file_size,
            created_by=actor,
        )

        write_platform_audit(
            event_type='tenant_backup',
            tenant_id=tenant_id,
            actor_username=actor,
            notes=f'Backup created: {backup_file.name}',
        )

        self.stdout.write(self.style.SUCCESS(f'Backup created: {backup_file}'))
