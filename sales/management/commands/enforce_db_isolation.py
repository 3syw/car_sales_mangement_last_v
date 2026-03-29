import json
import shutil
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from sales.models import PlatformTenant


class Command(BaseCommand):
    help = (
        "Audits tenant-data leakage into default DB and optionally cleans tenant business "
        "tables from default with safety backup."
    )

    PLATFORM_MODEL_NAMES = {
        'platformtenant',
        'globalauditlog',
        'tenantbackuprecord',
        'tenantmigrationrecord',
        'userthemepreference',
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Delete leaked sales business rows from default DB.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Required safety flag when using --cleanup.',
        )
        parser.add_argument(
            '--skip-backup',
            action='store_true',
            help='Skip automatic backup before cleanup (not recommended).',
        )
        parser.add_argument(
            '--report-path',
            default='',
            help='Optional custom report path (JSON).',
        )

    def handle(self, *args, **options):
        run_cleanup = bool(options.get('cleanup'))
        force = bool(options.get('force'))
        skip_backup = bool(options.get('skip_backup'))
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if run_cleanup and not force:
            raise CommandError('Cleanup requires --force for safety.')

        business_models = self._sales_business_models()
        if not business_models:
            raise CommandError('No sales business models detected for audit.')

        before_rows = self._collect_row_counts(business_models)
        total_before = sum(item['row_count'] for item in before_rows)

        self.stdout.write(self.style.NOTICE('Isolation audit started.'))
        self.stdout.write(f"Leaked tenant-business rows in default DB: {total_before}")

        cleanup_summary = {
            'requested': run_cleanup,
            'performed': False,
            'backup_file': None,
            'deleted_tables': [],
            'rows_before_cleanup': total_before,
            'rows_after_cleanup': total_before,
        }

        after_rows = before_rows

        if run_cleanup and total_before > 0:
            if not skip_backup:
                cleanup_summary['backup_file'] = str(self._backup_default_db(timestamp))
                self.stdout.write(self.style.SUCCESS(f"Backup created: {cleanup_summary['backup_file']}"))

            deleted_tables = self._cleanup_default_business_rows(business_models)
            after_rows = self._collect_row_counts(business_models)
            total_after = sum(item['row_count'] for item in after_rows)

            cleanup_summary.update({
                'performed': True,
                'deleted_tables': deleted_tables,
                'rows_after_cleanup': total_after,
            })

            if total_after == 0:
                self.stdout.write(self.style.SUCCESS('Default DB cleanup completed with full isolation.'))
            else:
                self.stdout.write(self.style.WARNING(
                    f"Cleanup finished but {total_after} business rows are still present in default DB."
                ))

        elif run_cleanup:
            cleanup_summary['performed'] = True
            cleanup_summary['rows_after_cleanup'] = 0
            self.stdout.write(self.style.SUCCESS('No leaked rows found. Nothing to clean.'))

        report = {
            'generated_at': datetime.now().isoformat(),
            'default_db_path': str(self._default_db_path()),
            'tenant_db_directory': str(Path(settings.BASE_DIR) / 'tenant_dbs'),
            'active_platform_tenants': PlatformTenant.objects.using('default').filter(is_active=True, is_deleted=False).count(),
            'default_auth_user_count': User.objects.using('default').count(),
            'before_cleanup': before_rows,
            'after_cleanup': after_rows,
            'cleanup': cleanup_summary,
        }

        report_path = self._resolve_report_path(options.get('report_path') or '', timestamp)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        self.stdout.write(self.style.SUCCESS(f'Report written: {report_path}'))

        if total_before > 0 and not run_cleanup:
            self.stdout.write(self.style.WARNING(
                'Leaked rows detected. Re-run with --cleanup --force to enforce strict separation.'
            ))

    def _sales_business_models(self):
        app_config = apps.get_app_config('sales')
        models = []
        for model in app_config.get_models():
            if not model._meta.managed:
                continue
            if model._meta.model_name in self.PLATFORM_MODEL_NAMES:
                continue
            models.append(model)
        return models

    def _collect_row_counts(self, models):
        rows = []
        table_names = self._default_table_names()
        for model in sorted(models, key=lambda m: m._meta.db_table):
            table = model._meta.db_table
            table_exists = table in table_names
            count = model.objects.using('default').count() if table_exists else 0
            rows.append({
                'model': model.__name__,
                'table': table,
                'row_count': count,
                'table_exists': table_exists,
            })
        return rows

    def _cleanup_default_business_rows(self, models):
        deleted_tables = []
        table_names = self._default_table_names()
        ordered_models = sorted(
            models,
            key=lambda m: (self._relation_score(m), m._meta.db_table),
            reverse=True,
        )

        with transaction.atomic(using='default'):
            for model in ordered_models:
                if model._meta.db_table not in table_names:
                    continue

                count_before = model.objects.using('default').count()
                if count_before <= 0:
                    continue

                model.objects.using('default').all().delete()
                deleted_tables.append({
                    'model': model.__name__,
                    'table': model._meta.db_table,
                    'rows_before_delete': count_before,
                })

        return deleted_tables

    def _default_table_names(self):
        return set(connections['default'].introspection.table_names())

    def _relation_score(self, model):
        score = 0
        for field in model._meta.get_fields():
            remote_field = getattr(field, 'remote_field', None)
            remote_model = getattr(remote_field, 'model', None)
            if remote_model is None:
                continue
            if getattr(remote_model._meta, 'app_label', '') == 'sales':
                score += 1
        return score

    def _default_db_path(self):
        raw_name = settings.DATABASES['default']['NAME']
        db_path = Path(raw_name)
        if not db_path.is_absolute():
            db_path = Path(settings.BASE_DIR) / db_path
        return db_path

    def _backup_default_db(self, timestamp):
        source_db = self._default_db_path()
        if not source_db.exists():
            raise CommandError(f'Default DB file not found: {source_db}')

        backup_dir = Path(settings.BASE_DIR) / 'backups' / 'default'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file = backup_dir / f'default_pre_isolation_cleanup_{timestamp}.sqlite3'
        shutil.copy2(source_db, backup_file)
        return backup_file

    def _resolve_report_path(self, report_path, timestamp):
        if report_path:
            resolved = Path(report_path)
            if not resolved.is_absolute():
                resolved = Path(settings.BASE_DIR) / resolved
            return resolved

        reports_dir = Path(settings.BASE_DIR) / 'reports'
        return reports_dir / f'db_isolation_report_{timestamp}.json'
