import os
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403


def _env(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and (value is None or str(value).strip() == ''):
        raise ImproperlyConfigured(f'Missing required environment variable: {name}')
    return value


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f'Environment variable {name} must be an integer.') from exc


def _env_list(name, default=None, required=False):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        values = default or []
        if required and not values:
            raise ImproperlyConfigured(f'Missing required environment variable: {name}')
        return values
    return [item.strip() for item in raw.split(',') if item.strip()]


DEBUG = False
SECRET_KEY = _env('DJANGO_SECRET_KEY', required=True)

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', required=True)
_default_csrf_origins = [
    f'https://{host}'
    for host in ALLOWED_HOSTS
    if host and host != '*' and '/' not in host
]
CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS', default=_default_csrf_origins)

_db_engine = (_env('DJANGO_DB_ENGINE', default='django.db.backends.postgresql') or '').strip().lower()
if _db_engine in {'postgres', 'postgresql', 'django.db.backends.postgresql'}:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _env('DJANGO_DB_NAME', required=True),
            'USER': _env('DJANGO_DB_USER', required=True),
            'PASSWORD': _env('DJANGO_DB_PASSWORD', required=True),
            'HOST': _env('DJANGO_DB_HOST', required=True),
            'PORT': _env('DJANGO_DB_PORT', default='5432'),
            'CONN_MAX_AGE': _env_int('DJANGO_DB_CONN_MAX_AGE', 60),
            'OPTIONS': {
                'connect_timeout': _env_int('DJANGO_DB_CONNECT_TIMEOUT', 10),
            },
        }
    }
elif _db_engine in {'sqlite', 'sqlite3', 'django.db.backends.sqlite3'}:
    sqlite_name = _env('DJANGO_SQLITE_NAME', default='db.sqlite3')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / sqlite_name,
            'CONN_MAX_AGE': _env_int('DJANGO_DB_CONN_MAX_AGE', 60),
        }
    }
else:
    raise ImproperlyConfigured(f'Unsupported DJANGO_DB_ENGINE value: {_db_engine}')

STATIC_ROOT = BASE_DIR / 'staticfiles'

SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
SESSION_COOKIE_SECURE = _env_bool('DJANGO_SESSION_COOKIE_SECURE', True)
CSRF_COOKIE_SECURE = _env_bool('DJANGO_CSRF_COOKIE_SECURE', True)
SESSION_COOKIE_HTTPONLY = _env_bool('DJANGO_SESSION_COOKIE_HTTPONLY', True)
SESSION_COOKIE_SAMESITE = _env('DJANGO_SESSION_COOKIE_SAMESITE', default='Lax')
CSRF_COOKIE_SAMESITE = _env('DJANGO_CSRF_COOKIE_SAMESITE', default='Lax')

SECURE_HSTS_SECONDS = _env_int('DJANGO_SECURE_HSTS_SECONDS', 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
SECURE_HSTS_PRELOAD = _env_bool('DJANGO_SECURE_HSTS_PRELOAD', True)
SECURE_CONTENT_TYPE_NOSNIFF = _env_bool('DJANGO_SECURE_CONTENT_TYPE_NOSNIFF', True)
SECURE_REFERRER_POLICY = _env('DJANGO_SECURE_REFERRER_POLICY', default='strict-origin-when-cross-origin')
X_FRAME_OPTIONS = _env('DJANGO_X_FRAME_OPTIONS', default='DENY')

USE_X_FORWARDED_HOST = _env_bool('DJANGO_USE_X_FORWARDED_HOST', True)
if _env_bool('DJANGO_USE_X_FORWARDED_PROTO', True):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

LOG_LEVEL = _env('DJANGO_LOG_LEVEL', default='INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
}

CELERY_BROKER_URL = _env('CELERY_BROKER_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = _env('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = _env_bool('CELERY_TASK_TRACK_STARTED', True)
CELERY_TASK_TIME_LIMIT = _env_int('CELERY_TASK_TIME_LIMIT', 60 * 30)
CELERY_TASK_SOFT_TIME_LIMIT = _env_int('CELERY_TASK_SOFT_TIME_LIMIT', 60 * 25)

CHANNEL_REDIS_URL = _env('CHANNEL_REDIS_URL', default='redis://127.0.0.1:6379/1')
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer' if CHANNEL_REDIS_URL == 'memory://' else 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [CHANNEL_REDIS_URL],
        } if CHANNEL_REDIS_URL != 'memory://' else {},
    }
}

WEBSOCKET_ALLOWED_ORIGINS = _env_list('DJANGO_WEBSOCKET_ALLOWED_ORIGINS', default=CSRF_TRUSTED_ORIGINS)

DJANGO_CACHE_URL = _env('DJANGO_CACHE_URL', default='locmem://default')
if DJANGO_CACHE_URL.startswith('redis://') or DJANGO_CACHE_URL.startswith('rediss://'):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': DJANGO_CACHE_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'car-sales-production-cache',
        }
    }

SIMPLE_JWT.update({
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=_env_int('JWT_ACCESS_TOKEN_MINUTES', 15)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=_env_int('JWT_REFRESH_TOKEN_DAYS', 7)),
    'ROTATE_REFRESH_TOKENS': _env_bool('JWT_ROTATE_REFRESH_TOKENS', True),
    'BLACKLIST_AFTER_ROTATION': _env_bool('JWT_BLACKLIST_AFTER_ROTATION', True),
    'AUDIENCE': _env('JWT_AUDIENCE', default='car-sales-clients'),
    'ISSUER': _env('JWT_ISSUER', default='car-sales-platform'),
})

REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].update({
    'anon': _env('DRF_THROTTLE_ANON', default='120/minute'),
    'user': _env('DRF_THROTTLE_USER', default='240/minute'),
    'auth_token_burst': _env('DRF_THROTTLE_AUTH_TOKEN_BURST', default='10/minute'),
    'auth_token_sustained': _env('DRF_THROTTLE_AUTH_TOKEN_SUSTAINED', default='60/hour'),
    'auth_refresh_burst': _env('DRF_THROTTLE_AUTH_REFRESH_BURST', default='20/minute'),
    'auth_refresh_sustained': _env('DRF_THROTTLE_AUTH_REFRESH_SUSTAINED', default='200/hour'),
})

SECURITY_EXPORT_WINDOW_SECONDS = _env_int('SECURITY_EXPORT_WINDOW_SECONDS', 600)
SECURITY_EXPORT_ALERT_THRESHOLD = _env_int('SECURITY_EXPORT_ALERT_THRESHOLD', 5)
SECURITY_PLATFORM_LOGIN_WINDOW_SECONDS = _env_int('SECURITY_PLATFORM_LOGIN_WINDOW_SECONDS', 900)
SECURITY_PLATFORM_LOGIN_MAX_ATTEMPTS = _env_int('SECURITY_PLATFORM_LOGIN_MAX_ATTEMPTS', 5)

GOOGLE_OAUTH_CLIENT_ID = _env('GOOGLE_OAUTH_CLIENT_ID', default='').strip()
GOOGLE_OAUTH_CLIENT_SECRET = _env('GOOGLE_OAUTH_CLIENT_SECRET', default='').strip()
GOOGLE_OAUTH_REDIRECT_URI = _env('GOOGLE_OAUTH_REDIRECT_URI', default='').strip()
GOOGLE_OAUTH_ENABLED = _env_bool('GOOGLE_OAUTH_ENABLED', False)
