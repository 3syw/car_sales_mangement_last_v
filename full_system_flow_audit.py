import json
import os
import uuid
from contextlib import contextmanager
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django

django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import ContentType, Permission
from django.test import Client

from sales.models import (
    Car,
    CarMaintenance,
    Customer,
    DebtPayment,
    FinanceVoucher,
    InterfaceAccess,
    OperationLog,
    PlatformTenant,
    Sale,
)
from sales.tenant_context import clear_current_tenant, set_current_tenant
from sales.tenant_database import ensure_tenant_connection, migrate_tenant_database, normalize_tenant_id


TENANT_ID = 'audit-flow-scan'
PLATFORM_OWNER_USERNAME = 'platform_audit_owner'
PLATFORM_OWNER_PASSWORD = 'Platform#Audit2026'


def unique_token(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@contextmanager
def tenant_context(tenant_id, alias):
    set_current_tenant(tenant_id, alias)
    try:
        yield
    finally:
        clear_current_tenant()


def ensure_tenant():
    tenant = PlatformTenant.objects.using('default').filter(tenant_id=TENANT_ID).first()
    if tenant is None:
        tenant = PlatformTenant(name='Audit Flow Tenant', tenant_id=TENANT_ID)
        tenant.save(using='default')
    else:
        tenant.is_active = True
        tenant.is_deleted = False
        tenant.save(using='default', update_fields=['is_active', 'is_deleted'])

    alias = migrate_tenant_database(TENANT_ID)
    ensure_tenant_connection(TENANT_ID)
    return tenant, alias


def ensure_platform_owner():
    User = get_user_model()
    owner = User.objects.using('default').filter(username=PLATFORM_OWNER_USERNAME).first()
    if owner is None:
        owner = User.objects.db_manager('default').create_superuser(
            username=PLATFORM_OWNER_USERNAME,
            email='',
            password=PLATFORM_OWNER_PASSWORD,
        )
    else:
        owner.is_staff = True
        owner.is_superuser = True
        owner.is_active = True
        owner.set_password(PLATFORM_OWNER_PASSWORD)
        owner.save(using='default')


def ensure_tenant_users(alias):
    User = get_user_model()

    role_specs = {
        'super': {
            'username': 'audit_super',
            'password': 'Audit#Super2026',
            'is_staff': True,
            'is_superuser': True,
            'interface_access': {
                'can_access_dashboard': True,
                'can_access_cars': True,
                'can_access_reports': True,
                'can_access_debts': True,
                'can_access_timeline': True,
                'can_access_system_users': True,
                'can_add_maintenance_expenses': True,
            },
        },
        'staff': {
            'username': 'audit_staff',
            'password': 'Audit#Staff2026',
            'is_staff': True,
            'is_superuser': False,
            'interface_access': {
                'can_access_dashboard': True,
                'can_access_cars': True,
                'can_access_reports': False,
                'can_access_debts': True,
                'can_access_timeline': True,
                'can_access_system_users': False,
                'can_add_maintenance_expenses': True,
            },
        },
        'sales': {
            'username': 'audit_sales',
            'password': 'Audit#Sales2026',
            'is_staff': False,
            'is_superuser': False,
            'interface_access': {
                'can_access_dashboard': True,
                'can_access_cars': True,
                'can_access_reports': False,
                'can_access_debts': False,
                'can_access_timeline': False,
                'can_access_system_users': False,
                'can_add_maintenance_expenses': False,
            },
        },
        'accountant': {
            'username': 'audit_accountant',
            'password': 'Audit#Accountant2026',
            'is_staff': False,
            'is_superuser': False,
            'interface_access': {
                'can_access_dashboard': True,
                'can_access_cars': True,
                'can_access_reports': True,
                'can_access_debts': True,
                'can_access_timeline': True,
                'can_access_system_users': False,
                'can_add_maintenance_expenses': True,
            },
        },
    }

    users = {}
    car_content_type = ContentType.objects.db_manager(alias).get(app_label='sales', model='car')
    car_permissions = {
        p.codename: p
        for p in Permission.objects.db_manager(alias).filter(
            content_type=car_content_type,
            codename__in=['view_car', 'add_car', 'change_car', 'delete_car'],
        )
    }

    for role_name, spec in role_specs.items():
        user = User.objects.using(alias).filter(username=spec['username']).first()
        if user is None:
            user = User.objects.db_manager(alias).create_user(
                username=spec['username'],
                password=spec['password'],
                email='',
            )

        user.is_staff = spec['is_staff']
        user.is_superuser = spec['is_superuser']
        user.is_active = True
        user.set_password(spec['password'])
        user.save(using=alias)

        if role_name == 'staff':
            user.user_permissions.clear()
            for codename in ['view_car', 'add_car', 'change_car']:
                permission = car_permissions.get(codename)
                if permission is not None:
                    user.user_permissions.add(permission)

        InterfaceAccess.objects.using(alias).update_or_create(
            user_id=user.id,
            defaults=spec['interface_access'],
        )

        users[role_name] = {
            'username': spec['username'],
            'password': spec['password'],
        }

    return users


def seed_business_data(tenant_id, alias):
    with tenant_context(tenant_id, alias):
        open_car = Car.objects.create(
            brand='Toyota',
            model_name='Camry',
            vin=(unique_token('OPENVIN').replace('-', '')[:17]).ljust(17, '1'),
            year=2023,
            cost_price=100000,
            selling_price=123000,
            currency='SR',
            is_sold=False,
        )

        sold_car = Car.objects.create(
            brand='Nissan',
            model_name='Sunny',
            vin=(unique_token('SOLDVIN').replace('-', '')[:17]).ljust(17, '2'),
            year=2022,
            cost_price=50000,
            selling_price=62000,
            currency='SR',
            is_sold=False,
        )

        customer = Customer.objects.create(
            name='عميل تدقيق',
            phone='0500000000',
            national_id=unique_token('NID')[:20],
        )

        sale = Sale.objects.create(
            car=sold_car,
            customer=customer,
            sale_price=62000,
            amount_paid=30000,
        )

    return {
        'open_car_id': open_car.id,
        'open_car_vin': open_car.vin,
        'sold_car_id': sold_car.id,
        'sold_sale_id': sale.id,
    }


def login_tenant(client, username, password, next_url='/dashboard/'):
    response = client.post(
        '/login/',
        {
            'tenant_id': TENANT_ID,
            'username': username,
            'password': password,
            'next': next_url,
        },
        follow=False,
    )
    return response


def create_jpeg_upload(filename='invoice.jpg'):
    from io import BytesIO
    from PIL import Image
    from django.core.files.uploadedfile import SimpleUploadedFile

    buffer = BytesIO()
    Image.new('RGB', (10, 10), color='blue').save(buffer, format='JPEG')
    return SimpleUploadedFile(filename, buffer.getvalue(), content_type='image/jpeg')


def run_audit():
    tenant, alias = ensure_tenant()
    ensure_platform_owner()
    users = ensure_tenant_users(alias)
    seed = seed_business_data(tenant.tenant_id, alias)

    report = {
        'tenant_id': tenant.tenant_id,
        'tenant_alias': alias,
        'checks': [],
        'anomalies': [],
        'summary': {},
    }

    def add_check(name, role, ok, details):
        item = {
            'name': name,
            'role': role,
            'ok': bool(ok),
            'details': details,
        }
        report['checks'].append(item)
        if not ok:
            report['anomalies'].append(item)

    route_expectations = {
        '/dashboard/': {'super': {200}, 'staff': {200}, 'sales': {200}, 'accountant': {200}},
        '/cars/': {'super': {200}, 'staff': {200}, 'sales': {200}, 'accountant': {200}},
        '/debts/': {'super': {200}, 'staff': {200}, 'sales': {403}, 'accountant': {200}},
        '/timeline/': {'super': {200}, 'staff': {200}, 'sales': {403}, 'accountant': {200}},
        '/reports/': {'super': {200}, 'staff': {403}, 'sales': {403}, 'accountant': {403}},
        '/reports/financial/': {'super': {200}, 'staff': {403}, 'sales': {403}, 'accountant': {403}},
        '/reports/vouchers/list/': {'super': {200}, 'staff': {403}, 'sales': {403}, 'accountant': {403}},
        '/admin/': {'super': {200, 302}, 'staff': {200, 302}, 'sales': {302}, 'accountant': {302}},
        '/admin/sales/car/add/': {'super': {200}, 'staff': {200}, 'sales': {302}, 'accountant': {302}},
        '/admin/sales/permissions/': {'super': {200}, 'staff': {403}, 'sales': {403}, 'accountant': {403}},
        '/admin/auth/user/list/': {'super': {200}, 'staff': {403}, 'sales': {403}, 'accountant': {403}},
        '/admin/sales/car/available/': {'super': {200}, 'staff': {200}, 'sales': {403}, 'accountant': {403}},
    }

    for role_name, credentials in users.items():
        client = Client()
        login_response = login_tenant(client, credentials['username'], credentials['password'])
        login_ok = login_response.status_code in {302}
        add_check(
            name='tenant_login',
            role=role_name,
            ok=login_ok,
            details={
                'status': login_response.status_code,
                'location': login_response.get('Location'),
            },
        )

        if not login_ok:
            continue

        session = client.session
        add_check(
            name='session_keys_after_login',
            role=role_name,
            ok=bool(session.get('tenant_id')) and bool(session.get('tenant_db_alias')),
            details={
                'tenant_id': session.get('tenant_id'),
                'tenant_db_alias': session.get('tenant_db_alias'),
            },
        )

        for path, expected_map in route_expectations.items():
            response = client.get(path, follow=False)
            expected = expected_map[role_name]
            ok = response.status_code in expected

            if path.startswith('/admin/') and role_name in {'sales', 'accountant'} and response.status_code == 302:
                ok = '/admin/login/' in (response.get('Location') or '')

            add_check(
                name=f'GET {path}',
                role=role_name,
                ok=ok,
                details={
                    'status': response.status_code,
                    'location': response.get('Location'),
                    'expected': sorted(expected),
                },
            )

        if role_name in {'sales', 'accountant'}:
            first = client.get('/admin/sales/car/add/', follow=False)
            second = None
            loop_detected = False
            if first.status_code == 302 and '/admin/login/' in (first.get('Location') or ''):
                second = client.get(first.get('Location'), follow=False)
                loop_detected = second.status_code == 302 and '/admin/sales/car/add/' in (second.get('Location') or '')

            add_check(
                name='nonstaff_admin_redirect_no_loop',
                role=role_name,
                ok=not loop_detected,
                details={
                    'first_status': first.status_code,
                    'first_location': first.get('Location'),
                    'second_status': None if second is None else second.status_code,
                    'second_location': None if second is None else second.get('Location'),
                },
            )

        if role_name in {'super', 'staff'}:
            before_default_logs = OperationLog.objects.using('default').count()
            vin = (unique_token(f'{role_name}-ADMINVIN').replace('-', '')[:17]).ljust(17, '3')
            response = client.post(
                '/admin/sales/car/add/',
                {
                    'brand': 'Toyota',
                    'model_name': 'Corolla',
                    'vin': vin,
                    'year': '2024',
                    'cost_price': '70000',
                    'cost_currency': 'SR',
                    'selling_price': '82000',
                    'currency': 'SR',
                    '_save': 'Save',
                },
                follow=False,
            )
            car_in_tenant = Car.objects.using(alias).filter(vin=vin).exists()
            car_in_default = Car.objects.using('default').filter(vin=vin).exists()
            after_default_logs = OperationLog.objects.using('default').count()

            add_check(
                name='admin_add_car_post',
                role=role_name,
                ok=response.status_code == 302 and '/admin/login/' not in (response.get('Location') or ''),
                details={'status': response.status_code, 'location': response.get('Location')},
            )
            add_check(
                name='admin_add_car_db_target',
                role=role_name,
                ok=car_in_tenant and not car_in_default,
                details={'saved_in_tenant': car_in_tenant, 'saved_in_default': car_in_default},
            )
            add_check(
                name='tenant_action_no_default_log_leak',
                role=role_name,
                ok=before_default_logs == after_default_logs,
                details={'before_default_logs': before_default_logs, 'after_default_logs': after_default_logs},
            )

            # session resilience check A: remove tenant_id keep alias
            session = client.session
            alias_value = session.get('tenant_db_alias')
            session.pop('tenant_id', None)
            session.save()

            resilient_vin_a = (unique_token(f'{role_name}-RSLA').replace('-', '')[:17]).ljust(17, '4')
            response_a = client.post(
                '/admin/sales/car/add/',
                {
                    'brand': 'Honda',
                    'model_name': 'Accord',
                    'vin': resilient_vin_a,
                    'year': '2024',
                    'cost_price': '88000',
                    'cost_currency': 'SR',
                    'selling_price': '99000',
                    'currency': 'SR',
                    '_save': 'Save',
                },
                follow=False,
            )
            add_check(
                name='resilience_missing_tenant_id',
                role=role_name,
                ok=response_a.status_code == 302 and '/admin/login/' not in (response_a.get('Location') or ''),
                details={'status': response_a.status_code, 'location': response_a.get('Location'), 'alias_kept': alias_value},
            )

            # session resilience check B: restore tenant_id and remove alias
            session = client.session
            session['tenant_id'] = TENANT_ID
            session.pop('tenant_db_alias', None)
            session.save()

            resilient_vin_b = (unique_token(f'{role_name}-RSLB').replace('-', '')[:17]).ljust(17, '5')
            response_b = client.post(
                '/admin/sales/car/add/',
                {
                    'brand': 'Kia',
                    'model_name': 'Cerato',
                    'vin': resilient_vin_b,
                    'year': '2024',
                    'cost_price': '65000',
                    'cost_currency': 'SR',
                    'selling_price': '77000',
                    'currency': 'SR',
                    '_save': 'Save',
                },
                follow=False,
            )
            add_check(
                name='resilience_missing_tenant_alias',
                role=role_name,
                ok=response_b.status_code == 302 and '/admin/login/' not in (response_b.get('Location') or ''),
                details={'status': response_b.status_code, 'location': response_b.get('Location')},
            )

        if role_name in {'super', 'staff', 'sales', 'accountant'}:
            open_car = Car.objects.using(alias).get(id=seed['open_car_id'])
            edit_response = client.post(
                f"/cars/edit/{open_car.id}/",
                {
                    'brand': open_car.brand,
                    'model_name': open_car.model_name,
                    'vin': open_car.vin,
                    'year': str(open_car.year),
                    'cost_price': str(open_car.cost_price),
                    'selling_price': str(open_car.selling_price),
                    'currency': open_car.currency,
                    'is_sold': 'on' if open_car.is_sold else '',
                },
                follow=False,
            )
            edit_ok = edit_response.status_code in {302} and '/login/' not in (edit_response.get('Location') or '')
            add_check(
                name='front_car_edit_post',
                role=role_name,
                ok=edit_ok,
                details={'status': edit_response.status_code, 'location': edit_response.get('Location')},
            )

        if role_name in {'super', 'accountant'}:
            # authorized maintenance add on open car
            before_count = CarMaintenance.objects.using(alias).count()
            maintenance_response = client.post(
                f"/cars/{seed['open_car_id']}/?tab=maintenance",
                {
                    'amount': '1500',
                    'maintenance_type': 'mechanical',
                    'operation_date': date.today().isoformat(),
                    'supplier_workshop': 'ورش التدقيق',
                    'payment_method': 'cash',
                    'invoice_image': create_jpeg_upload(),
                },
                follow=False,
            )
            after_count = CarMaintenance.objects.using(alias).count()
            add_check(
                name='maintenance_add_authorized',
                role=role_name,
                ok=maintenance_response.status_code == 302 and 'maintenance_saved=1' in (maintenance_response.get('Location') or '') and after_count == before_count + 1,
                details={
                    'status': maintenance_response.status_code,
                    'location': maintenance_response.get('Location'),
                    'before_count': before_count,
                    'after_count': after_count,
                },
            )

            # blocked maintenance on sold car
            sold_response = client.post(
                f"/cars/{seed['sold_car_id']}/?tab=maintenance",
                {
                    'amount': '900',
                    'maintenance_type': 'polish',
                    'operation_date': date.today().isoformat(),
                    'supplier_workshop': 'ورشة مغلقة',
                    'payment_method': 'bank',
                    'invoice_image': create_jpeg_upload('sold.jpg'),
                },
                follow=False,
            )
            add_check(
                name='maintenance_add_on_sold_blocked',
                role=role_name,
                ok=sold_response.status_code == 302 and 'maintenance_error=sold' in (sold_response.get('Location') or ''),
                details={'status': sold_response.status_code, 'location': sold_response.get('Location')},
            )

        if role_name == 'accountant':
            receipt_number = unique_token('SD')[:30]
            debt_response = client.post(
                f"/debts/{seed['sold_sale_id']}/add-payment/",
                {
                    'receipt_number': receipt_number,
                    'payment_date': date.today().isoformat(),
                    'paid_amount': '1000',
                },
                follow=False,
            )
            debt_ok = debt_response.status_code == 302 and 'debt_paid=1' in (debt_response.get('Location') or '')
            voucher_exists = FinanceVoucher.objects.using(alias).filter(voucher_number=receipt_number).exists()
            add_check(
                name='debt_payment_flow',
                role=role_name,
                ok=debt_ok and voucher_exists,
                details={
                    'status': debt_response.status_code,
                    'location': debt_response.get('Location'),
                    'voucher_created': voucher_exists,
                },
            )

        logout_response = client.get('/logout/', follow=False)
        add_check(
            name='logout_redirect',
            role=role_name,
            ok=logout_response.status_code == 302 and '/login/' in (logout_response.get('Location') or ''),
            details={'status': logout_response.status_code, 'location': logout_response.get('Location')},
        )

    # Platform owner flow
    platform_client = Client()
    platform_login = platform_client.post(
        '/admin/platform/login/',
        {'username': PLATFORM_OWNER_USERNAME, 'password': PLATFORM_OWNER_PASSWORD},
        follow=False,
    )
    add_check(
        name='platform_owner_login',
        role='platform_owner',
        ok=platform_login.status_code == 302 and '/admin/platform/switch-tenant/' in (platform_login.get('Location') or ''),
        details={'status': platform_login.status_code, 'location': platform_login.get('Location')},
    )

    switch_get = platform_client.get('/admin/platform/switch-tenant/', follow=False)
    add_check(
        name='platform_switch_page',
        role='platform_owner',
        ok=switch_get.status_code == 200,
        details={'status': switch_get.status_code},
    )

    switch_post = platform_client.post(
        '/admin/platform/switch-tenant/',
        {'tenant_id': TENANT_ID},
        follow=False,
    )
    add_check(
        name='platform_switch_tenant',
        role='platform_owner',
        ok=switch_post.status_code == 302 and 'switched=1' in (switch_post.get('Location') or ''),
        details={'status': switch_post.status_code, 'location': switch_post.get('Location')},
    )

    admin_add_get = platform_client.get('/admin/sales/car/add/', follow=False)
    add_check(
        name='platform_impersonated_admin_access',
        role='platform_owner',
        ok=admin_add_get.status_code == 200,
        details={'status': admin_add_get.status_code},
    )

    vin = (unique_token('PLATVIN').replace('-', '')[:17]).ljust(17, '6')
    admin_add_post = platform_client.post(
        '/admin/sales/car/add/',
        {
            'brand': 'Ford',
            'model_name': 'Explorer',
            'vin': vin,
            'year': '2024',
            'cost_price': '140000',
            'cost_currency': 'SR',
            'selling_price': '168000',
            'currency': 'SR',
            '_save': 'Save',
        },
        follow=False,
    )
    add_check(
        name='platform_impersonated_add_car',
        role='platform_owner',
        ok=admin_add_post.status_code == 302 and '/admin/login/' not in (admin_add_post.get('Location') or ''),
        details={'status': admin_add_post.status_code, 'location': admin_add_post.get('Location')},
    )

    exit_post = platform_client.post('/admin/platform/exit-tenant/', {}, follow=False)
    session_after_exit = platform_client.session
    add_check(
        name='platform_exit_impersonation',
        role='platform_owner',
        ok=exit_post.status_code == 302 and 'exited=1' in (exit_post.get('Location') or ''),
        details={
            'status': exit_post.status_code,
            'location': exit_post.get('Location'),
            'tenant_id_after_exit': session_after_exit.get('tenant_id'),
            'tenant_alias_after_exit': session_after_exit.get('tenant_db_alias'),
        },
    )

    total_checks = len(report['checks'])
    failed = len(report['anomalies'])
    passed = total_checks - failed

    report['summary'] = {
        'total_checks': total_checks,
        'passed': passed,
        'failed': failed,
    }

    report_path = 'flow_audit_report.json'
    with open(report_path, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print('=== FLOW AUDIT SUMMARY ===')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'Report file: {report_path}')

    if failed:
        print('=== ANOMALIES ===')
        for idx, anomaly in enumerate(report['anomalies'], start=1):
            print(f"{idx}. [{anomaly['role']}] {anomaly['name']} -> {anomaly['details']}")
    else:
        print('No anomalies detected in the audited transitions.')


if __name__ == '__main__':
    run_audit()
