import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from sales.consistency_checks import build_financial_consistency_report
from sales.models import PlatformTenant
from sales.tenant_database import ensure_tenant_connection, normalize_tenant_id


class Command(BaseCommand):
    help = 'Runs financial consistency checks and detects orphan/inconsistent accounting records.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', required=False, help='Optional tenant id to check a single tenant')
        parser.add_argument('--report-path', default='', help='Optional JSON report output path')

    def handle(self, *args, **options):
        tenant_id = normalize_tenant_id(options.get('tenant_id') or '')
        report_path = (options.get('report_path') or '').strip()

        reports = []

        if tenant_id:
            alias = ensure_tenant_connection(tenant_id)
            if not alias:
                raise CommandError(f'Unable to resolve tenant alias for {tenant_id}.')

            report = build_financial_consistency_report(alias=alias)
            reports.append({
                'tenant_id': tenant_id,
                **report,
            })
        else:
            tenants = PlatformTenant.objects.using('default').filter(is_active=True, is_deleted=False).order_by('tenant_id')
            if not tenants.exists():
                raise CommandError('No active tenants found.')

            for tenant in tenants:
                normalized_id = normalize_tenant_id(tenant.tenant_id)
                alias = ensure_tenant_connection(normalized_id)
                if not alias:
                    continue

                report = build_financial_consistency_report(alias=alias)
                reports.append({
                    'tenant_id': normalized_id,
                    **report,
                })

        if not reports:
            raise CommandError('No consistency report data was generated.')

        overall_issues = sum(item.get('total_issues', 0) for item in reports)

        for item in reports:
            self.stdout.write(
                f"[{item['tenant_id']}] issues={item['total_issues']} status={'clean' if item['is_clean'] else 'review'}"
            )

        self.stdout.write(self.style.SUCCESS(f'Total detected issues across reports: {overall_issues}'))

        if report_path:
            output = Path(report_path)
            if not output.is_absolute():
                output = Path(settings.BASE_DIR) / output
        else:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output = Path(settings.BASE_DIR) / 'reports' / f'financial_consistency_report_{timestamp}.json'

        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'generated_at': datetime.now().isoformat(),
            'reports': reports,
            'total_issues': overall_issues,
        }
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

        self.stdout.write(self.style.SUCCESS(f'JSON report written: {output}'))
