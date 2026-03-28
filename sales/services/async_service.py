from celery.result import AsyncResult

from sales.tasks import (
    build_tenant_reports_snapshot_task,
    run_db_isolation_audit_task,
    run_financial_consistency_report_task,
    run_tenant_backup_task,
)


class AsyncService:
    @staticmethod
    def queue_financial_consistency_report(*, tenant_id='', report_path=''):
        return run_financial_consistency_report_task.delay(
            tenant_id=tenant_id or '',
            report_path=report_path or '',
        )

    @staticmethod
    def queue_tenant_backup(*, tenant_id, actor='system'):
        return run_tenant_backup_task.delay(tenant_id=tenant_id, actor=actor or 'system')

    @staticmethod
    def queue_db_isolation_audit(*, cleanup=False, force=False, skip_backup=False, report_path=''):
        return run_db_isolation_audit_task.delay(
            cleanup=bool(cleanup),
            force=bool(force),
            skip_backup=bool(skip_backup),
            report_path=report_path or '',
        )

    @staticmethod
    def queue_reports_snapshot(*, tenant_id):
        return build_tenant_reports_snapshot_task.delay(tenant_id=tenant_id)

    @staticmethod
    def get_task_status(task_id):
        task = AsyncResult(task_id)
        payload = {
            'task_id': task_id,
            'status': task.status,
            'ready': task.ready(),
            'successful': task.successful() if task.ready() else False,
        }
        if task.ready():
            payload['result'] = task.result
        return payload
