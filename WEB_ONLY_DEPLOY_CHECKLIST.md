# Web-Only Deployment Checklist

This checklist is for the current phase where deployment target is web-only (Django web + API).

## 1) Environment

- Set `DJANGO_SETTINGS_MODULE=core.settings_production`
- Set a strong `DJANGO_SECRET_KEY` (50+ chars, random)
- Set `DJANGO_ALLOWED_HOSTS` with real domains
- Configure production database variables (`DJANGO_DB_*`), preferably PostgreSQL
- Configure Redis URLs if Celery is enabled (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`)
- Configure Google OAuth variables if Google login is used

## 2) Security validation

- Run:

```powershell
python manage.py check --deploy --settings=core.settings_production
```

- Expected: no issues

## 3) Database migrations

- Run default DB migrations:

```powershell
python manage.py migrate --settings=core.settings_production
```

- Run tenant schema migrations:

```powershell
python manage.py migrate_all_tenants
```

- Confirm migration status:

```powershell
python manage.py showmigrations --settings=core.settings_production
```

## 4) Static files

- Run:

```powershell
python manage.py collectstatic --noinput --settings=core.settings_production
```

## 5) Process runtime

- Start Django app process (example):

```bash
gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

- If async/background jobs are used, run Celery worker:

```bash
celery -A core worker --loglevel=info
```

## 6) Reverse proxy / HTTPS

- Enable HTTPS termination at proxy/load balancer
- Forward `X-Forwarded-Proto` and `X-Forwarded-Host`
- Ensure domain and TLS certificate are active

## 7) Web-only policy checks

- Desktop client is on hold in this phase
- Do not run/publish Electron desktop builds
- Keep deployment and operations focused on web runtime only

## 8) Post-deploy smoke tests

- Open login page and authenticate tenant user
- Verify dashboard loads without errors
- Verify API authentication (`/api/auth/token/`) and a protected endpoint
- Verify file uploads/media access path
- Verify at least one background task (if Celery enabled)
- Verify audit logs and security alerts appear as expected

## 9) Rollback readiness

- Keep last working DB backup before production migration
- Keep previous app release artifact/image ready for rollback
- Document rollback command path in hosting platform
