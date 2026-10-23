#!/usr/bin/env bash
# Render build script: install, collect static files, migrate, seed configuration, create the first admin.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed_initial
python manage.py ensure_superuser

if [ "${SEED_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo
fi
