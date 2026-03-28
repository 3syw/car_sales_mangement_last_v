import os


def configure_django_entrypoint_defaults():
    """Provide non-crashing defaults for serverless autodetected entrypoints.

    These defaults keep the app bootable when host env vars are missing.
    Override them in production with real environment variables.
    """
    settings_module = (os.getenv('DJANGO_SETTINGS_MODULE') or '').strip()
    if not settings_module:
        os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings_production'

    selected = (os.getenv('DJANGO_SETTINGS_MODULE') or '').strip()
    if selected != 'core.settings_production':
        return

    # Keep production settings bootable even when platform env vars are not configured yet.
    os.environ.setdefault('DJANGO_SECRET_KEY', 'insecure-vercel-bootstrap-key-change-me')
    os.environ.setdefault('DJANGO_ALLOWED_HOSTS', '.vercel.app,localhost,127.0.0.1')
    os.environ.setdefault('DJANGO_CSRF_TRUSTED_ORIGINS', 'https://*.vercel.app,http://localhost,http://127.0.0.1')

    # Use ephemeral sqlite by default in serverless preview if DB vars are absent.
    os.environ.setdefault('DJANGO_DB_ENGINE', 'django.db.backends.sqlite3')
    os.environ.setdefault('DJANGO_SQLITE_NAME', '/tmp/db.sqlite3')
