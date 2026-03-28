"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from deploy_bootstrap import configure_django_entrypoint_defaults
from .settings_bootstrap import configure_settings

configure_django_entrypoint_defaults()
configure_settings('core.settings_production')

application = get_wsgi_application()
