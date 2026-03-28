import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
django.setup()
from django.test import Client
c = Client()
c.login(username='mgr', password='pass')
resp = c.get('/')
print('status', resp.status_code)
print(resp.content.decode()[:200])
