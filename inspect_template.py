import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings')
django.setup()
from django.template import loader

t = loader.get_template('admin/login.html')
print('origin:', t.origin)
print('name:', t.name)
print('loader:', type(t.loader))
print('dirs used:', t.origin.name if hasattr(t.origin,'name') else 'no name')
print('template content first lines:')
print(t.template.source.splitlines()[:20])
