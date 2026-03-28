import os

SETTINGS_ENV_VAR = 'DJANGO_SETTINGS_MODULE'


def configure_settings(default_module):
    """Resolve and set the Django settings module with an explicit fallback."""
    configured = (os.getenv(SETTINGS_ENV_VAR) or '').strip()
    selected = configured or default_module
    os.environ.setdefault(SETTINGS_ENV_VAR, selected)
    return selected
