release: python manage.py migrate --noinput && python manage.py seed_initial
web: gunicorn config.wsgi:application -c gunicorn.conf.py
