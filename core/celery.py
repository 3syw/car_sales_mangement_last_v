from celery import Celery

from .settings_bootstrap import configure_settings


configure_settings('core.settings')

app = Celery('core')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    return {
        'task_id': self.request.id,
        'status': 'ok',
    }
