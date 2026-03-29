#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./release_production.sh [ENV_FILE]
# Example:
#   ./release_production.sh env.production

ENV_FILE="${1:-env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] Environment file not found: $ENV_FILE"
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

echo "[1/6] Pulling latest code"
git pull

echo "[2/6] Installing dependencies"
pip install -r requirements.txt

echo "[3/7] Running default DB migrations"
python manage.py migrate --settings=core.settings_production

echo "[4/7] Running tenant DB migrations"
python manage.py migrate_all_tenants --settings=core.settings_production

echo "[5/7] Collecting static files"
python manage.py collectstatic --noinput --settings=core.settings_production

echo "[6/7] Running deploy checks"
python manage.py check --deploy --settings=core.settings_production

echo "[7/7] Deployment tasks completed"
echo "Restart app services now (gunicorn/celery/nginx) according to your host setup."
