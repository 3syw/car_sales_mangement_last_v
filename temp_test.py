import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
django.setup()
from django.test import Client
c = Client()
r = c.get('/signup/')
print('status', r.status_code)
print(r.content.decode()[:1000])
