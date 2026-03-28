import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
django.setup()
from django.test import Client
from django.contrib.auth.models import User

if not User.objects.filter(username='mgr').exists():
    User.objects.create_superuser('mgr','mgr@example.com','pass')

c = Client()
r = c.get('/admin/login/')
print('GET status', r.status_code)
print('GET snippet starts', r.content.decode()[:500])

r = c.post('/admin/login/?next=/admin/', {'username':'mgr','password':'pass'})
print('POST status', r.status_code)
print('redirect', r.get('Location'))
print('cookies', r.cookies)
print('POST content snippet:', r.content.decode()[:500])
