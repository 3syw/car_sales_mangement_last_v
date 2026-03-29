# Deployment Settings Guide

## Web-Only Deployment Mode (Current Phase)

This project is currently deployed as **web-only**.

- Production deployment target: Django web app/API only.
- Desktop client under `desktop-client/` is intentionally on hold.
- Do not run or publish Electron desktop builds in this phase.

Reason:
- reduce deployment complexity
- speed up production rollout
- focus on stability, security, and operations in one runtime

## 1) Set production settings module
Use `core.settings_production` in your process environment.

Note:
- The project now uses a shared settings bootstrap across `manage.py`, `core/wsgi.py`, and `core/asgi.py`.
- If `DJANGO_SETTINGS_MODULE` is unset:
	- `manage.py` falls back to `core.settings` (development-safe local default).
	- `wsgi.py` and `asgi.py` fall back to `core.settings_production` (production-safe server default).
- Best practice remains to set `DJANGO_SETTINGS_MODULE` explicitly in all environments.

PowerShell:

```powershell
$env:DJANGO_SETTINGS_MODULE = "core.settings_production"
```

Linux/bash:

```bash
export DJANGO_SETTINGS_MODULE=core.settings_production
```

## 2) Configure environment variables
Start from `env.production.example` and provide real values.

Critical variables:
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- database variables (`DJANGO_DB_*`)
- `DJANGO_CACHE_URL` (use Redis in production to make security throttles consistent across workers)

## 3) Validate deploy security checks

```bash
python manage.py check --deploy --settings=core.settings_production
```

## 4) Run migrations and collect static files

```bash
python manage.py migrate --settings=core.settings_production
python manage.py collectstatic --noinput --settings=core.settings_production
```

## 5) Start Gunicorn behind Nginx
Example process command:

```bash
gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

Ensure Nginx forwards `X-Forwarded-Proto` and `X-Forwarded-Host` headers.

Auto-detect hosting note:
- Some Git-based hosts scan only the repository root for Django entrypoints.
- This repository now includes root-level `app.py`, `wsgi.py`, and `asgi.py` wrappers that forward to `core.wsgi` / `core.asgi`.
- If the host asks for a startup target, prefer `app:app` or `wsgi:application`.

## 6) Enable Redis + Celery workers

Install dependencies (once):

```bash
pip install -r requirements.txt
```

Start Redis service (example local host/port `127.0.0.1:6379`) and make sure
`CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are set in environment.

Start Celery worker:

```bash
celery -A core worker --loglevel=info --pool=solo
```

Optional: Start Celery beat for scheduled jobs when needed:

```bash
celery -A core beat --loglevel=info
```

Important:
- Celery workers must use the same `DJANGO_SETTINGS_MODULE` and environment values as Django app.
- For Windows hosts, `--pool=solo` is recommended for worker compatibility.
