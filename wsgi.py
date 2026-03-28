import os
import sys
from pathlib import Path
from deploy_bootstrap import configure_django_entrypoint_defaults

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
	sys.path.insert(0, str(ROOT_DIR))

configure_django_entrypoint_defaults()

from core.wsgi import application
