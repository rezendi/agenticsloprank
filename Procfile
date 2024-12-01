web: gunicorn yamllms.wsgi
worker: python manage.py rqworker
release: ./manage.py migrate --no-input
