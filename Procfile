web: python manage.py migrate && python manage.py create_admin_user && gunicorn CineShow.wsgi:application --bind 0.0.0.0:$PORT
