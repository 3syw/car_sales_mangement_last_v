from django.test import Client
from django.conf import settings
print('DEBUG', settings.DEBUG)
c = Client()
resp = c.get('/admin/login/')
print('status', resp.status_code)
print(resp.content[:2000])
