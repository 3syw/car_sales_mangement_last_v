import os

import django


def run_diagnostic():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    django.setup()

    from django.contrib.auth.models import User
    from django.test import Client

    User.objects.filter(username='admin1').delete()
    User.objects.create_superuser('admin1', 'a@a.com', 'pass')

    client = Client()
    logged = client.login(username='admin1', password='pass')
    print('logged', logged)

    User.objects.filter(username='bob').delete()
    user = User.objects.create_user('bob', 'bob@example.com', 'pass')
    response = client.get(f'/admin/auth/user/{user.id}/change/')
    print(response.status_code)

    with open('full_output.html', 'w', encoding='utf-8') as output_file:
        output_file.write(response.content.decode())
    print('wrote full_output.html')


if __name__ == '__main__':
    run_diagnostic()
