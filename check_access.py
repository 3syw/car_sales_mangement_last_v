import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
django.setup()
from django.test import Client
from django.contrib.auth.models import User

c=Client()
for username in ['mgr','sales','acct']:
    try:
        u=User.objects.get(username=username)
        print('testing',username)
        logged=c.login(username=username,password='pass')
        print(' login success',logged)
        for path in ['/','/dashboard/','/cars/','/reports/','/debts/']:
            r=c.get(path)
            print('  ',path,r.status_code)
        c.logout()
    except User.DoesNotExist:
        print('user not exist',username)
